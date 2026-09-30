from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.access.models import ApiKey
from app.access.ratelimit import InMemoryRateLimiter
from app.audit_usage.models import AuditLog
from app.organizations.models import Membership, MembershipRole
from tests.access_helpers import bearer, seed_tenant
from tests.api.test_text_search_api import create_organization, login, search_api  # noqa: F401


@pytest.fixture()
def admin_api(search_api):  # noqa: F811
    client, factory, gateway = search_api
    login(client, gateway, code="owner", email="owner@example.test", subject="owner")
    org = create_organization(client)
    client.app.state.rate_limiter = InMemoryRateLimiter()
    return client, factory, org


def test_key_lifecycle_is_one_time_fail_closed_and_audited(admin_api):
    client, factory, org = admin_api
    path = f"/organizations/{org}"
    created = client.post(path + "/api-keys", json={"name": "Automation", "scopes": ["search:read"]})
    assert created.status_code == 201, created.text
    key = created.json()
    assert key["key"].startswith("arq_")
    assert client.get("/v1/whoami", headers=bearer(key["key"])).status_code == 401
    assert client.put(path + "/access-settings", json={"public_api_enabled": True}).status_code == 200
    assert client.get("/v1/whoami", headers=bearer(key["key"])).status_code == 200
    listed = client.get(path + "/api-keys").json()
    assert listed[0]["id"] == key["id"] and "key" not in listed[0] and "secret_hash" not in listed[0]
    assert client.delete(path + f'/api-keys/{key["id"]}').status_code == 204
    assert client.get("/v1/whoami", headers=bearer(key["key"])).status_code == 401
    with factory() as session:
        actions = list(session.scalars(select(AuditLog).where(AuditLog.organization_id == org)))
        assert {row.action for row in actions} >= {"api_key.created", "api_key.revoked", "access_settings.updated"}
        owner = session.scalar(select(Membership).where(Membership.organization_id == org))
        assert all(row.actor_user_id == owner.user_id for row in actions)
        assert session.get(ApiKey, UUID(key["id"])).revoked_at is not None


def test_member_and_foreign_organization_cannot_manage_keys(admin_api):
    client, factory, org = admin_api
    with factory.begin() as session:
        session.query(Membership).filter_by(organization_id=org).update({"role": MembershipRole.MEMBER})
    for method, suffix, payload in (("GET", "/api-keys", None), ("POST", "/api-keys", {"name": "x", "scopes": ["search:read"]}), ("PUT", "/access-settings", {"public_api_enabled": True})):
        assert client.request(method, f"/organizations/{org}" + suffix, json=payload).status_code == 403
    assert client.get(f"/organizations/{uuid4()}/api-keys").status_code == 403


def test_scope_node_expiry_and_csrf_validation(admin_api):
    client, factory, org = admin_api
    foreign = seed_tenant(factory, "Foreign", "secret")
    from app.library.models import LibraryNode
    with factory() as session:
        node = session.scalar(select(LibraryNode).where(LibraryNode.organization_id == foreign.organization_id, LibraryNode.kind == "file"))
        node_id = str(node.id)
    path = f"/organizations/{org}/api-keys"
    for payload in ({"name": "x", "scopes": ["admin:all"]}, {"name": "x", "scopes": ["search:read"], "node_ids": [node_id]}, {"name": "x", "scopes": ["search:read"], "expires_at": "2000-01-01T00:00:00Z"}):
        assert client.post(path, json=payload).status_code == 422
    assert client.post(path, json={"name": "x", "scopes": ["search:read"]}, headers={"Origin": "https://evil.example"}).status_code == 403
    client.cookies.clear()
    assert client.get(path).status_code == 401


def test_listed_key_dates_have_explicit_timezone(admin_api):
    from datetime import UTC, datetime, timedelta
    client, _factory, org = admin_api
    path = f"/organizations/{org}/api-keys"
    expires = datetime.now(UTC) + timedelta(days=1)
    assert client.post(path, json={"name": "expiring", "scopes": ["search:read"],
                                   "expires_at": expires.isoformat()}).status_code == 201
    value = client.get(path).json()[0]["expires_at"]
    assert value.endswith(("Z", "+00:00"))


def test_browser_preflight_allows_access_switch_put(admin_api):
    client, _factory, org = admin_api
    response = client.options(f"/organizations/{org}/access-settings", headers={
        "Origin": client.app.state.settings.public_app_url,
        "Access-Control-Request-Method": "PUT",
        "Access-Control-Request-Headers": "content-type",
    })
    assert response.status_code == 200
    assert "PUT" in response.headers["access-control-allow-methods"]


def test_review_14_one_time_key_response_is_never_cached(admin_api):
    client, _factory, org = admin_api
    response = client.post(f'/organizations/{org}/api-keys', json={'name': 'x', 'scopes': ['search:read']})
    assert response.status_code == 201
    assert response.headers.get('Cache-Control') == 'no-store'
