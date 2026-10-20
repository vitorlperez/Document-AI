"""T-I1/T-I2 for MCP: the connection reads what its linked user's Spaces allow, and reports Spaces."""

import pytest

from app.access.models import McpConnection, OrganizationAccessSettings
from app.identity.models import AuthIdentity
from app.spaces.models import SpaceMember
from tests.api.test_mcp_server import (  # noqa: F401 -- reuse the MCP harness fixtures
    _make_client,
    _token,
    call,
    factory,
    private_key,
)
from tests.spaces_helpers import seed_world


@pytest.fixture()
def world(factory, private_key):  # noqa: F811
    with factory.begin() as session:
        world = seed_world(session)
        session.add(OrganizationAccessSettings(organization_id=world.organization_id, public_api_enabled=True,
                                               mcp_enabled=True))
        for who in ("eva", "bruno"):
            session.add(AuthIdentity(user_id=world.users[who], provider="workos", provider_subject=who,
                                     verified_email=f"{who}@acme.test"))
            session.add(McpConnection(organization_id=world.organization_id, user_id=world.users[who]))
    return world


@pytest.fixture()
def client(factory, private_key):  # noqa: F811
    with _make_client(factory, private_key) as c:
        yield c


def test_a_connection_cannot_search_or_fetch_outside_its_users_spaces(client, world, private_key):  # noqa: F811
    token = _token(private_key, "eva")  # owner, member of Geral only
    found = call(client, token, "search", {"query": "reajuste"})["result"]["structuredContent"]["results"]
    assert found == []
    fetched = call(client, token, "fetch", {"id": str(world.documents["diretoria"])})["result"]
    assert fetched["isError"] is True
    ok = call(client, token, "fetch", {"id": str(world.documents["politicas"])})["result"]
    assert ok["isError"] is False


def test_entering_the_space_opens_it_on_the_next_call(client, world, private_key, factory):  # noqa: F811
    token = _token(private_key, "eva")
    assert call(client, token, "search", {"query": "reajuste"})["result"]["structuredContent"]["results"] == []
    with factory.begin() as session:
        session.add(SpaceMember(organization_id=world.organization_id, space_id=world.spaces["diretoria"],
                                user_id=world.users["eva"], role="member"))
    results = call(client, token, "search", {"query": "reajuste"})["result"]["structuredContent"]["results"]
    assert [r["id"] for r in results] == [str(world.documents["diretoria"])]
    assert [s["name"] for s in results[0]["spaces"]] == ["Diretoria"]


def test_list_sources_and_search_report_spaces_and_space_ids_narrows(client, world, private_key):  # noqa: F811
    token = _token(private_key, "bruno")
    sources = call(client, token, "list_sources", {})["result"]["structuredContent"]["sources"]
    assert {s["name"]: [x["name"] for x in s["spaces"]] for s in sources} == {"politicas": ["Geral"], "rh": ["RH"]}
    both = call(client, token, "search", {"query": "politica"})["result"]["structuredContent"]["results"]
    assert {r["title"] for r in both} == {"politicas.pdf", "rh.pdf"}
    only_rh = call(client, token, "search", {"query": "politica", "space_ids": [str(world.spaces["rh"])]})
    assert [r["title"] for r in only_rh["result"]["structuredContent"]["results"]] == ["rh.pdf"]


def test_a_space_that_is_not_the_users_does_not_exist(client, world, private_key):  # noqa: F811
    token = _token(private_key, "bruno")
    foreign = call(client, token, "search", {"query": "politica", "space_ids": [str(world.spaces["diretoria"])]})
    assert foreign["result"]["isError"] is True
    malformed = call(client, token, "search", {"query": "politica", "space_ids": ["nope"]})
    assert malformed["result"]["isError"] is True
