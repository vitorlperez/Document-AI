"""Pontes Conversa <-> Biblioteca: /library/locate resolves a node or a cited document, fail-closed."""

from uuid import uuid4

from tests.api.test_library_space_badges_api import (
    as_user,
    get,
    world_api,  # noqa: F401 -- fixture
)
from tests.api.test_text_search_api import search_api  # noqa: F401 -- fixture dependency


def test_locate_by_document_returns_mention_and_ancestors(world_api):  # noqa: F811
    client, _, gateway, world = world_api
    as_user(client, gateway, "carla")
    body = get(client, world, "/library/locate", document_id=world.documents["diretoria"]).json()
    assert body["mention"]["node_id"] == str(world.nodes["diretoria"])
    assert body["mention"]["kind"] == "file" and body["mention"]["name"] == "diretoria.pdf"
    assert body["mention"]["source_provider"] == "google_drive"
    assert body["parent_id"] == str(world.nodes["source"])
    assert [item["id"] for item in body["ancestors"]] == [str(world.nodes["source"])]
    same = get(client, world, "/library/locate", node_id=world.nodes["diretoria"]).json()
    assert same["mention"] == body["mention"]


def test_not_visible_or_unknown_is_the_same_404(world_api):  # noqa: F811
    client, _, gateway, world = world_api
    as_user(client, gateway, "bruno")  # no Diretoria Space
    hidden = get(client, world, "/library/locate", document_id=world.documents["diretoria"])
    hidden_node = get(client, world, "/library/locate", node_id=world.nodes["diretoria"])
    missing = get(client, world, "/library/locate", document_id=uuid4())
    assert hidden.status_code == hidden_node.status_code == missing.status_code == 404
    assert hidden.json() == hidden_node.json() == missing.json() == {"detail": "library node not found"}
    assert get(client, world, "/library/locate", node_id=world.nodes["rh"]).status_code == 200


def test_space_filter_and_foreign_space_and_bad_params(world_api):  # noqa: F811
    client, _, gateway, world = world_api
    as_user(client, gateway, "bruno")
    assert get(client, world, "/library/locate", node_id=world.nodes["politicas"], space_ids=world.spaces["rh"]).status_code == 404
    assert get(client, world, "/library/locate", node_id=world.nodes["rh"], space_ids=world.spaces["rh"]).status_code == 200
    foreign = get(client, world, "/library/locate", node_id=world.nodes["rh"], space_ids=world.spaces["diretoria"])
    assert foreign.status_code == 404 and foreign.json() == {"detail": "space not found"}
    assert get(client, world, "/library/locate").status_code == 422
