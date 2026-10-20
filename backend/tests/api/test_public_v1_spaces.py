"""T-I1/T-I2: an API key reaches exactly U(linked user) ∩ node_ids, and reports Spaces."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.access.models import ApiAuditEvent, OrganizationAccessSettings
from app.access.ratelimit import InMemoryRateLimiter
from app.organizations.models import Membership, MembershipRole
from app.spaces.models import SpaceMember
from tests.access_helpers import Tenant, bearer, mint_key
from tests.api.test_text_search_api import (
    search_api,  # noqa: F401 -- reuse the isolated API fixture
)
from tests.spaces_helpers import seed_world


@pytest.fixture()
def world_api(search_api):  # noqa: F811
    client, factory, _gateway = search_api
    client.app.state.rate_limiter = InMemoryRateLimiter()
    with factory.begin() as session:
        world = seed_world(session)
        session.add(OrganizationAccessSettings(organization_id=world.organization_id, public_api_enabled=True,
                                               mcp_enabled=True))
        # Ana is an org admin and a manager of RH only: her key must reach RH + Geral, never Diretoria
        session.query(Membership).filter_by(user_id=world.users["ana"]).update({"role": MembershipRole.ADMIN})
    return client, factory, world


def key_for(factory, world, who, **kwargs):
    tenant = Tenant(world.organization_id, world.users[who], world.folders["politicas"], world.documents["politicas"])
    return mint_key(factory, tenant, **kwargs)


def search(client, key, term, **extra):
    return client.post("/v1/search", json={"query": term, **extra}, headers=bearer(key))


def test_admin_who_is_not_in_the_space_cannot_read_it_even_with_an_unrestricted_key(world_api):
    client, factory, world = world_api
    key = key_for(factory, world, "eva")  # owner, member of Geral only
    assert search(client, key, "reajuste").json()["results"] == []  # Diretoria-only term
    assert [r["id"] for r in search(client, key, "ferias").json()["results"]] == [str(world.documents["politicas"])]
    sources = client.get("/v1/sources", headers=bearer(key)).json()["sources"]
    assert [s["name"] for s in sources] == ["politicas"]
    assert client.get(f"/v1/documents/{world.documents['diretoria']}", headers=bearer(key)).status_code == 404


def test_key_scoped_to_a_node_outside_my_spaces_is_denied_uniformly(world_api):
    client, factory, world = world_api
    key = key_for(factory, world, "eva", node_ids=[world.nodes["diretoria"]])
    response = search(client, key, "reajuste")
    assert response.status_code == 404 and response.json() == {"detail": "not found"}


def test_entering_the_space_opens_the_same_requests(world_api):
    client, factory, world = world_api
    key = key_for(factory, world, "eva")
    assert search(client, key, "reajuste").json()["results"] == []
    with factory.begin() as session:
        session.add(SpaceMember(organization_id=world.organization_id, space_id=world.spaces["diretoria"],
                                user_id=world.users["eva"], role="member"))
    assert [r["id"] for r in search(client, key, "reajuste").json()["results"]] == [str(world.documents["diretoria"])]
    assert client.get(f"/v1/documents/{world.documents['diretoria']}", headers=bearer(key)).status_code == 200


def test_removing_the_person_from_a_space_narrows_the_key_on_the_next_request(world_api):
    client, factory, world = world_api
    key = key_for(factory, world, "ana")
    assert search(client, key, "salarial").json()["results"]
    with factory.begin() as session:
        session.query(SpaceMember).filter_by(space_id=world.spaces["rh"], user_id=world.users["ana"]).update(
            {"removed_at": datetime.now(UTC)})
    assert search(client, key, "salarial").json()["results"] == []  # same token, no re-issue
