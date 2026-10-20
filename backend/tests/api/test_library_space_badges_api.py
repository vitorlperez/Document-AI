"""T-E1: library endpoints carry the caller's Space badges and accept a space_ids narrowing."""

import pytest
from sqlalchemy import event

from app.knowledge.models import Document
from app.library.models import LibraryNode
from tests.api.test_text_search_api import (  # noqa: F401 -- reuse the isolated API fixture
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
        # the RH file is also indexed in the Geral scope
        session.add(Document(
            organization_id=world.organization_id, workspace_folder_id=world.folders["politicas"],
            external_file_id="rh-doc", name="rh.pdf", mime_type="application/pdf", source_url="u",
            content_hash="d" * 64, processing_version="v1", index_status="indexed"))
    return client, factory, gateway, world


def as_user(client, gateway, who):
    client.cookies.clear()
    login(client, gateway, code=who, email=f"{who}@acme.test", subject=who)


def get(client, world, path, **params):
    query = "&".join([f"organization_id={world.organization_id}"] + [f"{k}={v}" for k, v in params.items()])
    return client.get(f"{path}{'&' if '?' in path else '?'}{query}")


def badges(items):
    return {item["name"]: [s["name"] for s in item["spaces"]] for item in items}


def test_children_carry_only_the_callers_spaces_and_each_file_once(world_api):
    client, _, gateway, world = world_api
    root = world.nodes["source"]
    as_user(client, gateway, "carla")
    items = get(client, world, f"/library/nodes/{root}/children").json()["items"]
    assert badges(items) == {"politicas.pdf": ["Geral"], "rh.pdf": ["Geral", "RH"], "diretoria.pdf": ["Diretoria"]}
    as_user(client, gateway, "daniel")
    items = get(client, world, f"/library/nodes/{root}/children").json()["items"]
    assert badges(items) == {"politicas.pdf": ["Geral"], "rh.pdf": ["Geral"], "diretoria.pdf": ["Diretoria"]}


def test_roots_and_search_and_mentions_carry_badges(world_api):
    client, _, gateway, world = world_api
    as_user(client, gateway, "bruno")
    roots = get(client, world, "/library").json()["items"]
    assert [[s["name"] for s in r["spaces"]] for r in roots] == [["Geral", "RH"]]
    found = get(client, world, "/library/search", query="pdf").json()["items"]
    assert badges(found) == {"politicas.pdf": ["Geral"], "rh.pdf": ["Geral", "RH"]}
    mentions = get(client, world, "/library/mention-candidates", q="pdf").json()["items"]
    assert {m["name"]: [s["name"] for s in m["spaces"]] for m in mentions if m["kind"] == "file"} == {
        "politicas.pdf": ["Geral"], "rh.pdf": ["Geral", "RH"]}


def test_space_ids_narrows_every_endpoint_and_a_foreign_space_is_404(world_api):
    client, _, gateway, world = world_api
    rh, diretoria = world.spaces["rh"], world.spaces["diretoria"]
    root = world.nodes["source"]
    as_user(client, gateway, "bruno")
    items = get(client, world, f"/library/nodes/{root}/children", space_ids=rh).json()["items"]
    assert badges(items) == {"rh.pdf": ["RH"]}
    assert set(badges(get(client, world, "/library/search", query="pdf", space_ids=rh).json()["items"])) == {"rh.pdf"}
    mentions = get(client, world, "/library/mention-candidates", q="pdf", space_ids=rh).json()["items"]
    assert {m["name"] for m in mentions if m["kind"] == "file"} == {"rh.pdf"}
    assert [r["name"] for r in get(client, world, "/library", space_ids=rh).json()["items"]] == ["Google Drive"]
    for path, extra in ((f"/library/nodes/{root}/children", {}), ("/library/search", {"query": "pdf"}),
                        ("/library", {}), ("/library/mention-candidates", {"q": "pdf"})):
        response = get(client, world, path, space_ids=diretoria, **extra)
        assert response.status_code == 404 and response.json() == {"detail": "space not found"}, path


def test_statement_count_does_not_grow_with_the_page(world_api):
    client, factory, gateway, world = world_api
    root = world.nodes["source"]
    as_user(client, gateway, "carla")
    seen: list[str] = []
    engine = factory.kw["bind"]
    listener = lambda c, cur, st, p, ctx, m: seen.append(st)
    event.listen(engine, "before_cursor_execute", listener)
    try:
        get(client, world, f"/library/nodes/{root}/children")
        small = len(seen)
        with factory.begin() as session:
            source_id = session.get(LibraryNode, root).source_id
            for index in range(60):
                session.add(LibraryNode(organization_id=world.organization_id, source_id=source_id, parent_id=root,
                                        external_id=f"bulk-{index}", kind="file", name=f"bulk-{index}.pdf"))
                session.add(Document(
                    organization_id=world.organization_id, workspace_folder_id=world.folders["rh"],
                    external_file_id=f"bulk-{index}", name=f"bulk-{index}.pdf", mime_type="application/pdf",
                    source_url="u", content_hash="e" * 64, processing_version="v1", index_status="indexed"))
        seen.clear()
        items = get(client, world, f"/library/nodes/{root}/children", page_size=100).json()["items"]
        assert len(items) == 63
        assert len(seen) <= small + 1, (small, len(seen))
    finally:
        event.remove(engine, "before_cursor_execute", listener)
