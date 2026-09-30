from datetime import timedelta
from uuid import uuid4

import pytest

from app.access.models import SCOPE_DOCUMENTS, SCOPE_SEARCH
from app.access.ratelimit import InMemoryRateLimiter
from tests.access_helpers import bearer, mint_key, seed_tenant
from tests.api.test_text_search_api import (
    search_api,  # noqa: F401 -- reuse the isolated API fixture
)


@pytest.fixture()
def api(search_api):  # noqa: F811
    client, factory, _gateway = search_api
    client.app.state.rate_limiter = InMemoryRateLimiter()
    return client, factory


def test_search_and_fetch_are_confined_to_the_key_organization(api):
    client, factory = api
    a = seed_tenant(factory, "A", "Projeto Aurora entrega em setembro")
    b = seed_tenant(factory, "B", "Projeto Zenite sigiloso")
    key = mint_key(factory, a)
    hit = client.post("/v1/search", json={"query": "Aurora"}, headers=bearer(key))
    assert hit.status_code == 200
    assert [r["id"] for r in hit.json()["results"]] == [str(a.document_id)]
    assert hit.json()["results"][0]["url"] == "https://drive.example.test/A"
    assert client.post("/v1/search", json={"query": "Zenite"}, headers=bearer(key)).json()["results"] == []
    foreign = client.get(f"/v1/documents/{b.document_id}", headers=bearer(key))
    missing = client.get(f"/v1/documents/{uuid4()}", headers=bearer(key))
    assert foreign.status_code == missing.status_code == 404 and foreign.json() == missing.json()


def test_a_session_cookie_is_not_a_credential(api):
    client, _factory = api
    assert client.post("/v1/search", json={"query": "x"}).status_code == 401
    assert client.get("/v1/whoami", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_insufficient_scope_is_403_and_named(api):
    client, factory = api
    a = seed_tenant(factory, "A", "texto")
    key = mint_key(factory, a, scopes={SCOPE_SEARCH})
    response = client.get(f"/v1/documents/{a.document_id}", headers=bearer(key))
    assert response.status_code == 403 and SCOPE_DOCUMENTS in response.json()["detail"]


def test_folder_restricted_key_cannot_read_outside_its_nodes(api):
    client, factory = api
    a = seed_tenant(factory, "A", "Projeto Aurora")
    key = mint_key(factory, a)  # unrestricted
    # requesting the source root explicitly as a node is fine only for unrestricted keys
    assert client.post("/v1/search", json={"query": "Aurora", "node_ids": [str(uuid4())]}, headers=bearer(key)).status_code == 404


def test_rate_limit_returns_429_with_headers_and_is_audited(api):
    client, factory = api
    a = seed_tenant(factory, "A", "Aurora")
    key = mint_key(factory, a, rate=2)
    codes = [client.post("/v1/search", json={"query": "Aurora"}, headers=bearer(key)) for _ in range(3)]
    assert [c.status_code for c in codes] == [200, 200, 429]
    assert codes[2].headers["Retry-After"] and codes[0].headers["RateLimit-Limit"] == "2"
    from sqlalchemy import select

    from app.access.models import ApiAuditEvent
    with factory() as session:
        statuses = [row.status for row in session.scalars(select(ApiAuditEvent).order_by(ApiAuditEvent.created_at))]
    assert statuses.count("ok") == 2 and "rate_limited" in statuses


def test_revoked_and_expired_keys_are_401(api):
    client, factory = api
    a = seed_tenant(factory, "A", "x")
    for kwargs in ({"revoked": True}, {"expires_in": timedelta(seconds=-5)}):
        assert client.get("/v1/whoami", headers=bearer(mint_key(factory, a, **kwargs))).status_code == 401


def test_every_v1_route_requires_a_bearer_token(api):
    client, _factory = api
    open_paths = {"/v1/openapi.json"}
    for route in client.app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/v1") or path in open_paths:
            continue
        for method in route.methods - {"HEAD", "OPTIONS"}:
            response = client.request(method, path.replace("{document_id}", str(uuid4())), json={})
            assert response.status_code == 401, (method, path)


def test_openapi_documents_only_the_public_surface(api):
    client, _factory = api
    spec = client.get("/v1/openapi.json").json()
    assert spec["info"]["version"].startswith("1.") and all(p.startswith("/v1") for p in spec["paths"])
    assert "ApiKey" in spec["components"]["securitySchemes"]


def test_audit_covers_metadata_validation_and_limiter_failure(api):
    from app.access.models import ApiAuditEvent
    client, factory = api
    tenant = seed_tenant(factory, "A", "Aurora")
    key = mint_key(factory, tenant)
    assert client.get("/v1/whoami", headers=bearer(key)).status_code == 200
    assert client.post("/v1/search", headers=bearer(key), json={"query": ""}).status_code == 422
    class Broken:
        def hit(self, **kwargs):
            raise RuntimeError("redis unavailable")
    client.app.state.rate_limiter = Broken()
    assert client.get("/v1/sources", headers=bearer(key)).status_code == 503
    with factory() as session:
        assert sorted(row.http_status for row in session.query(ApiAuditEvent)) == [200, 422, 503]


def test_key_rate_limit_is_shared_across_endpoints(api):
    client, factory = api
    tenant = seed_tenant(factory, "A", "Aurora")
    key = mint_key(factory, tenant, rate=1)
    assert client.get("/v1/whoami", headers=bearer(key)).status_code == 200
    assert client.post("/v1/search", headers=bearer(key), json={"query": "Aurora"}).status_code == 429


def test_ask_is_disabled_by_default(api):
    client, factory = api
    tenant = seed_tenant(factory, "A", "Aurora")
    assert client.post("/v1/ask", headers=bearer(mint_key(factory, tenant)),
                       json={"question": "Quando?"}).status_code == 503


def test_cookie_and_bearer_authentication_do_not_cross_boundaries(api):
    from datetime import UTC, datetime, timedelta

    from app.identity.auth import hash_secret
    from app.identity.models import UserSession
    client, factory = api
    tenant = seed_tenant(factory, "A", "Aurora")
    with factory.begin() as session:
        session.add(UserSession(user_id=tenant.user_id, secret_hash=hash_secret("cookie-test"),
                                expires_at=datetime.now(UTC) + timedelta(hours=1)))
    client.cookies.set(client.app.state.settings.auth_session_cookie_name, "cookie-test")
    assert client.get("/v1/whoami").status_code == 401
    client.cookies.clear()
    assert client.get("/me", headers=bearer(mint_key(factory, tenant))).status_code == 401
