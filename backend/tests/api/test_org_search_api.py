"""T-E4: POST /organizations/{id}/search, content search over the caller's Spaces."""

import pytest

from tests.api.test_text_search_api import FakeSemanticProvider, login, search_api  # noqa: F401
from tests.space_derived_helpers import add_shared_copy
from tests.spaces_helpers import bind_login_identities, seed_world


@pytest.fixture()
def world_api(search_api):  # noqa: F811
    client, factory, gateway = search_api
    with factory.begin() as session:
        world = seed_world(session)
        bind_login_identities(session, world)
        add_shared_copy(session, world)
    client.app.state.semantic_provider = FakeSemanticProvider()
    return client, factory, gateway, world


def as_user(client, gateway, who):
    client.cookies.clear()
    login(client, gateway, code=who, email=f"{who}@acme.test", subject=who)


def search(client, world, query, **extra):
    return client.post(f"/organizations/{world.organization_id}/search", json={"query": query, **extra})


def names(response):
    return {item["title"] for item in response.json()["results"]}


def test_carla_finds_reajuste_with_the_space_seal(world_api):
    client, _, gateway, world = world_api
    as_user(client, gateway, "carla")
    body = search(client, world, "reajuste").json()
    assert [item["spaces"] for item in body["results"]] == [[{"id": str(world.spaces["diretoria"]), "name": "Diretoria"}]]


def test_daniel_never_sees_rh_and_bruno_never_sees_diretoria(world_api):
    client, _, gateway, world = world_api
    as_user(client, gateway, "daniel")
    assert "rh.pdf" not in names(search(client, world, "salarial"))
    assert names(search(client, world, "reajuste")) == {"diretoria.pdf"}
    as_user(client, gateway, "bruno")
    assert names(search(client, world, "reajuste")) == set()


def test_space_ids_narrow_and_a_foreign_space_is_404(world_api):
    client, _, gateway, world = world_api
    as_user(client, gateway, "carla")
    assert names(search(client, world, "politica", space_ids=[str(world.spaces["rh"])])) == {"rh.pdf"}
    as_user(client, gateway, "bruno")
    denied = search(client, world, "politica", space_ids=[str(world.spaces["diretoria"])])
    assert denied.status_code == 404 and denied.json() == {"detail": "space not found"}


def test_the_same_file_in_two_spaces_is_one_result_with_both_seals(world_api):
    client, _, gateway, world = world_api
    as_user(client, gateway, "carla")
    hits = [r for r in search(client, world, "calendario ferias").json()["results"]
            if r["title"] == "ferias-compartilhado.pdf"]
    assert len(hits) == 1 and sorted(s["name"] for s in hits[0]["spaces"]) == ["Geral", "RH"]


def test_limit_is_capped_and_snippets_are_untrusted_content(world_api):
    client, factory, gateway, world = world_api
    from app.knowledge.models import DocumentChunk
    with factory.begin() as session:
        chunk = session.query(DocumentChunk).filter_by(workspace_folder_id=world.folders["politicas"], position=0).first()
        chunk.text = "politica de ferias\u200b com texto oculto"
        chunk.search_text = chunk.text.lower()
    as_user(client, gateway, "carla")
    assert search(client, world, "politica", limit=500).status_code == 422
    body = search(client, world, "politica", limit=20).json()
    assert len(body["results"]) <= 20
    assert body["metadata"]["content_trust"] == "untrusted_document_content"
    assert all("\u200b" not in item["snippet"] for item in body["results"])


def test_non_members_and_anonymous_are_refused(world_api):
    client, _, _gateway, world = world_api
    client.cookies.clear()
    assert search(client, world, "politica").status_code == 401
