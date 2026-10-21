"""T-G3 / acceptance criterion 1: an organization migrated to "Geral" answers exactly as before.

Recorded in ``off`` (no Space rows at all), then ``backfill_default_spaces`` + ``enforce``; the responses must be
identical, apart from the new informative ``spaces`` field."""

import pytest

from app.access.models import OrganizationAccessSettings
from app.access.ratelimit import InMemoryRateLimiter
from app.organizations.models import Organization
from app.spaces.backfill import backfill_default_spaces
from app.spaces.models import Space, SpaceFolderGrant, SpaceMember
from tests.access_helpers import Tenant, bearer, mint_key
from tests.api.test_text_search_api import login, search_api  # noqa: F401
from tests.space_derived_helpers import CiteEverythingProvider
from tests.spaces_helpers import bind_login_identities, seed_world


@pytest.fixture()
def legacy_world(search_api):  # noqa: F811
    client, factory, gateway = search_api
    client.app.state.rate_limiter = InMemoryRateLimiter()
    client.app.state.semantic_provider = CiteEverythingProvider()
    with factory.begin() as session:
        world = seed_world(session, mode="off")
        bind_login_identities(session, world)
        for model in (SpaceFolderGrant, SpaceMember, Space):  # an organization from before Spaces existed
            session.query(model).delete()
        session.add(OrganizationAccessSettings(organization_id=world.organization_id, public_api_enabled=True,
                                               mcp_enabled=True))
    return client, factory, gateway, world


def strip_spaces(value):
    if isinstance(value, dict):
        return {k: strip_spaces(v) for k, v in value.items() if k != "spaces"}
    if isinstance(value, list):
        return [strip_spaces(v) for v in value]
    return value


def record(client, factory, gateway, world, who):
    client.cookies.clear()
    login(client, gateway, code=who, email=f"{who}@acme.test", subject=who)
    org, params = f"/organizations/{world.organization_id}", {"organization_id": str(world.organization_id)}
    roots = client.get("/library", params=params)
    source_id = roots.json()["items"][0]["id"]
    recorded = {
        "roots": roots,
        "children": client.get(f"/library/nodes/{source_id}/children", params=params),
        "library_search": client.get("/library/search", params={**params, "query": "pdf"}),
        "contexts": client.get("/library/question-contexts", params=params),
        "mentions": client.get("/library/mention-candidates", params=params),
        "search": client.post(f"{org}/search", json={"query": "ferias"}),
        "folders": client.get("/workspace-folders", params=params),
    }
    answer = client.post(f"{org}/questions", json={"question": "politica de ferias", "scope": "selection",
                                                   "providers": ["google_drive"]})
    body = answer.json()
    recorded["answer"] = body["answer"], sorted(c["document_name"] for c in body["citations"])
    out = {name: (r.status_code, strip_spaces(r.json())) for name, r in recorded.items() if name != "answer"}
    out["answer"] = recorded["answer"]
    return out


def v1_sources(client, factory, world):
    key = mint_key(factory, Tenant(world.organization_id, world.users["eva"], world.folders["politicas"],
                                   world.documents["politicas"]))
    client.cookies.clear()
    response = client.get("/v1/sources", headers=bearer(key))
    return response.status_code, strip_spaces(response.json())


@pytest.mark.parametrize("who", ["eva", "bruno"])
def test_geral_only_organization_is_indistinguishable_before_and_after_enforce(legacy_world, who):
    client, factory, gateway, world = legacy_world
    before = record(client, factory, gateway, world, who)
    before_v1 = v1_sources(client, factory, world)
    assert before["roots"][0] == 200 and before["answer"][1]

    with factory.begin() as session:
        assert backfill_default_spaces(session.connection()) == 1
        session.get(Organization, world.organization_id).spaces_resolver_mode = "enforce"

    assert record(client, factory, gateway, world, who) == before
    assert v1_sources(client, factory, world) == before_v1
