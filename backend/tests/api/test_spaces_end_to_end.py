"""T-G1: the full Spaces flow through HTTP. An admin removes Bruno from RH and every live surface lets go at once."""

import pytest
from sqlalchemy import select

from app.access.models import OrganizationAccessSettings
from app.access.ratelimit import InMemoryRateLimiter
from app.knowledge.derived_visibility import HIDDEN_NOTICE
from app.knowledge.models import DocumentChunk
from app.organizations.models import Membership, MembershipRole
from tests.access_helpers import Tenant, bearer, mint_key
from tests.api.test_text_search_api import login, search_api  # noqa: F401
from tests.space_derived_helpers import CiteEverythingProvider
from tests.spaces_helpers import bind_login_identities, seed_world


@pytest.fixture()
def world_api(search_api):  # noqa: F811
    client, factory, gateway = search_api
    client.app.state.rate_limiter = InMemoryRateLimiter()
    with factory.begin() as session:
        world = seed_world(session)
        bind_login_identities(session, world)
        # Bruno is an org admin who reads RH through the Space: only admins can hold an API key
        session.query(Membership).filter_by(user_id=world.users["bruno"]).update({"role": MembershipRole.ADMIN})
        session.add(OrganizationAccessSettings(organization_id=world.organization_id, public_api_enabled=True,
                                               mcp_enabled=True))
    client.app.state.semantic_provider = CiteEverythingProvider()
    return client, factory, gateway, world


def as_user(client, gateway, who):
    client.cookies.clear()
    login(client, gateway, code=who, email=f"{who}@acme.test", subject=who)


def v1(client, method, path, key, **kwargs):
    """/v1 is credentialed by the key alone: no session cookie rides along."""
    cookies = dict(client.cookies)
    client.cookies.clear()
    try:
        return getattr(client, method)(path, headers=bearer(key), **kwargs)
    finally:
        client.cookies.update(cookies)


def surfaces(client, factory, world, key):
    """Every live surface Bruno can use, reduced to whether it still shows the RH document."""
    org, rh_doc = f"/organizations/{world.organization_id}", world.documents["rh"]
    tree = client.get("/library", params={"organization_id": str(world.organization_id)})
    contexts = client.get("/library/question-contexts", params={"organization_id": str(world.organization_id)})
    mentions = client.get("/library/mention-candidates", params={"organization_id": str(world.organization_id)})
    found = client.post(f"{org}/search", json={"query": "salarial"})
    asked = client.post(f"{org}/questions", json={"question": "politica salarial", "scope": "selection",
                                                  "providers": ["google_drive"]})
    with factory() as session:
        chunk_id = session.scalar(select(DocumentChunk.id).where(DocumentChunk.document_id == rh_doc))
    return {
        "tree": "rh" in str(tree.json()).lower(),
        "contexts": "rh" in str(contexts.json()).lower().replace("politicas", ""),
        "mentions": "rh.pdf" in str(mentions.json()),
        "search": bool(found.json().get("results")),
        "chat": "rh.pdf" in str(asked.json()),
        "evidence": client.get(f"{org}/documents/{rh_doc}/evidence", params={"chunk_id": str(chunk_id)}).status_code == 200,
        "viewer": client.get(f"{org}/documents/{rh_doc}/view").status_code == 200,
        "v1_search": bool(v1(client, "post", "/v1/search", key, json={"query": "salarial"}).json().get("results")),
        "v1_document": v1(client, "get", f"/v1/documents/{rh_doc}", key).status_code == 200,
    }


def test_admin_removes_bruno_from_rh_and_every_live_surface_lets_go(world_api):
    client, factory, gateway, world = world_api
    tenant = Tenant(world.organization_id, world.users["bruno"], world.folders["politicas"], world.documents["politicas"])
    key = mint_key(factory, tenant)
    as_user(client, gateway, "bruno")
    conversation = client.post(f"/organizations/{world.organization_id}/questions", json={
        "question": "politica salarial", "scope": "selection", "providers": ["google_drive"]}).json()
    before = surfaces(client, factory, world, key)
    assert before["search"] and before["evidence"] and before["v1_search"] and before["v1_document"]

    as_user(client, gateway, "eva")  # the owner takes Bruno out of RH, through the API
    removed = client.delete(
        f"/organizations/{world.organization_id}/spaces/{world.spaces['rh']}/members/{world.users['bruno']}")
    assert removed.status_code == 204, removed.text

    as_user(client, gateway, "bruno")
    after = surfaces(client, factory, world, key)
    assert not any(after.values()), f"surfaces still showing RH: {[k for k, v in after.items() if v]}"
    messages = client.get(
        f"/organizations/{world.organization_id}/conversations/{conversation['conversation_id']}").json()["messages"]
    assert messages[1]["content"] == HIDDEN_NOTICE  # the stored answer that cited RH is hidden, not deleted
    assert "salarial" not in str(messages[1])
