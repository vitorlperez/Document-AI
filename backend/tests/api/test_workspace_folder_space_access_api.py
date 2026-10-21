"""T-B5: folder routes read by Space, operate by organization role (ADR-0021 D5/I7)."""

from uuid import UUID

import pytest

from app.knowledge.models import Document
from tests.api.test_text_search_api import (  # noqa: F401 -- reuse the isolated API fixture
    FakeSemanticProvider,
    login,
    search_api,
)
from tests.spaces_helpers import bind_login_identities, seed_world


@pytest.fixture()
def world_api(search_api):  # noqa: F811
    client, factory, gateway = search_api
    with factory.begin() as session:
        world = seed_world(session)
        bind_login_identities(session, world)
        failed = Document(
            organization_id=world.organization_id, workspace_folder_id=world.folders["rh"],
            external_file_id="rh-broken", name="salarios-secretos.pdf", mime_type="application/pdf",
            source_url="https://drive.example.test/rh-broken", content_hash="b" * 64, processing_version="v1",
            index_status="failed", error_code="extraction_failed")
        session.add(failed)
        session.flush()
        failed_id = failed.id
    client.app.state.semantic_provider = FakeSemanticProvider()
    return client, factory, gateway, world, failed_id


def as_user(client, gateway, who):
    client.cookies.clear()
    login(client, gateway, code=who, email=f"{who}@acme.test", subject=who)


def url(world, folder, suffix):
    return f"/workspace-folders/{world.folders[folder]}/{suffix}?organization_id={world.organization_id}"


def test_member_outside_the_space_gets_404_on_search_and_questions(world_api):
    client, _, gateway, world, _ = world_api
    as_user(client, gateway, "bruno")
    assert client.post(url(world, "diretoria", "search"), json={"query": "reajuste"}).status_code == 404
    assert client.post(url(world, "diretoria", "questions"), json={"question": "reajuste?"}).status_code == 404
    assert client.post(url(world, "rh", "search"), json={"query": "salarial"}).status_code == 200


def test_member_lists_documents_of_own_space_but_not_of_others(world_api):
    client, _, gateway, world, _ = world_api
    as_user(client, gateway, "bruno")
    own = client.get(url(world, "rh", "documents"))
    assert own.status_code == 200 and [item["name"] for item in own.json()] == ["rh.pdf"]
    assert client.get(url(world, "diretoria", "documents")).status_code == 404


def test_admin_who_is_not_a_member_sees_counts_but_no_file_names(world_api):
    client, _, gateway, world, _ = world_api
    as_user(client, gateway, "eva")
    response = client.get(url(world, "rh", "documents"))
    assert response.status_code == 200
    body = response.json()
    assert body["readable"] is False
    assert body["counts"]["indexed"] == 1 and body["counts"]["failed"] == 1
    assert "rh.pdf" not in response.text and "salarios" not in response.text
    assert all("name" not in item for item in body["items"])
    readable = client.get(url(world, "politicas", "documents"))  # eva IS in Geral
    assert [item["name"] for item in readable.json()] == ["politicas.pdf"]


def test_admin_failures_hide_file_names_outside_own_spaces(world_api):
    client, _, gateway, world, failed_id = world_api
    as_user(client, gateway, "eva")
    response = client.get(url(world, "rh", "documents/failures"))
    assert response.status_code == 200
    [item] = response.json()
    assert item["error_code"] == "extraction_failed"
    assert item["name"] == f"arquivo #{str(failed_id)[:7]}"
    assert item["source_url"] is None
    assert "salarios" not in response.text


def test_non_admin_cannot_read_failures_and_stays_forbidden_for_operations(world_api):
    client, _, gateway, world, failed_id = world_api
    as_user(client, gateway, "bruno")
    assert client.get(url(world, "rh", "documents/failures")).status_code == 403
    assert client.delete(url(world, "rh", f"documents/{failed_id}")).status_code == 403


def test_admin_can_still_operate_on_a_folder_of_a_space_they_are_not_in(world_api):
    client, _, gateway, world, _ = world_api
    as_user(client, gateway, "eva")
    assert client.delete(url(world, "rh", f"documents/{world.documents['rh']}")).status_code == 204


def test_unknown_or_foreign_folder_is_404_not_403(world_api):
    client, _, gateway, world, _ = world_api
    as_user(client, gateway, "bruno")
    missing = UUID(int=1)
    assert client.post(f"/workspace-folders/{missing}/search?organization_id={world.organization_id}",
                       json={"query": "x"}).status_code == 404


def test_unknown_folder_is_a_uniform_404_for_members_and_403_for_outsiders(world_api):
    """B3 (decision 2026-10-20): Spaces always enforce, so the uniform 404 has no `off` exception any more."""
    from uuid import uuid4

    client, factory, gateway, world, _ = world_api
    ghost = f"/workspace-folders/{uuid4()}/search?organization_id={world.organization_id}"
    as_user(client, gateway, "bruno")
    assert client.post(ghost, json={"query": "x"}).status_code == 404
