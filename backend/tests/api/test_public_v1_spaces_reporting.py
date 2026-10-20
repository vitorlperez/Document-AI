"""T-I2: Spaces in the public API (whoami, sources, search, key reach preview)."""

from sqlalchemy import select

from app.access.models import ApiAuditEvent, OrganizationAccessSettings
from app.access.ratelimit import InMemoryRateLimiter
from app.organizations.models import Membership, MembershipRole
from tests.access_helpers import Tenant, bearer, mint_key
from tests.api.test_text_search_api import (
    search_api,  # noqa: F401 -- reuse the isolated API fixture
)
from tests.spaces_helpers import seed_world
import pytest


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


def key_for(factory, world, who, **kwargs):
    tenant = Tenant(world.organization_id, world.users[who], world.folders["politicas"], world.documents["politicas"])
    return mint_key(factory, tenant, **kwargs)


def search(client, key, term, **extra):
    return client.post("/v1/search", json={"query": term, **extra}, headers=bearer(key))


def test_whoami_and_sources_report_the_linked_users_spaces(world_api):
    client, factory, world = world_api
    key = key_for(factory, world, "ana")
    whoami = client.get("/v1/whoami", headers=bearer(key)).json()
    assert [s["name"] for s in whoami["spaces"]] == ["Geral", "RH"]
    sources = {s["name"]: [x["name"] for x in s["spaces"]] for s in client.get("/v1/sources", headers=bearer(key)).json()["sources"]}
    assert sources == {"politicas": ["Geral"], "rh": ["RH"]}


def test_search_reports_spaces_and_space_ids_narrows_or_404s(world_api):
    client, factory, world = world_api
    key = key_for(factory, world, "ana")
    both = search(client, key, "politica").json()["results"]
    assert {r["title"]: [s["name"] for s in r["spaces"]] for r in both} == {"politicas.pdf": ["Geral"], "rh.pdf": ["RH"]}
    only_rh = search(client, key, "politica", space_ids=[str(world.spaces["rh"])]).json()["results"]
    assert [r["title"] for r in only_rh] == ["rh.pdf"]
    foreign = search(client, key, "politica", space_ids=[str(world.spaces["diretoria"])])
    assert foreign.status_code == 404 and foreign.json() == {"detail": "space not found"}


def test_audit_never_stores_space_names(world_api):
    client, factory, world = world_api
    key = key_for(factory, world, "ana")
    search(client, key, "politica", space_ids=[str(world.spaces["rh"])])
    with factory() as session:
        rows = session.scalars(select(ApiAuditEvent)).all()
    dump = " ".join(str(vars(row)) for row in rows)
    assert rows and "RH" not in dump.replace("rh.pdf", "") and "Diretoria" not in dump


def test_key_creation_previews_the_creators_reach(world_api):
    client, factory, world = world_api
    from tests.api.test_text_search_api import login
    client.cookies.clear()
    gateway = client.app.state.auth_gateway
    with factory.begin() as session:
        from tests.spaces_helpers import bind_login_identities
        bind_login_identities(session, world)
    login(client, gateway, code="ana", email="ana@acme.test", subject="ana")
    response = client.post(f"/organizations/{world.organization_id}/api-keys",
                           json={"name": "k", "scopes": ["search:read"]})
    assert response.status_code == 201
    reach = response.json()["reach"]
    assert sorted(s["name"] for s in reach["spaces"]) == ["Geral", "RH"]
    assert reach["documents"] == 2


def test_key_listing_carries_the_same_reach_as_creation(world_api):
    client, factory, world = world_api
    from tests.api.test_text_search_api import login
    client.cookies.clear()
    gateway = client.app.state.auth_gateway
    with factory.begin() as session:
        from tests.spaces_helpers import bind_login_identities
        bind_login_identities(session, world)
    login(client, gateway, code="ana", email="ana@acme.test", subject="ana")
    base = f"/organizations/{world.organization_id}/api-keys"
    created = client.post(base, json={"name": "k", "scopes": ["search:read"]}).json()
    listed = client.get(base).json()
    assert listed[0]["id"] == created["id"] and "key" not in listed[0]
    assert listed[0]["reach"] == created["reach"]
    client.delete(f"{base}/{created['id']}")
    assert "reach" not in client.get(base).json()[0]  # revoked keys read nothing: no promise
