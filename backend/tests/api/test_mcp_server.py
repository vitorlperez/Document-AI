import json
import time
from datetime import UTC, datetime

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from app.access.models import ApiAuditEvent, McpConnection
from app.access.ratelimit import InMemoryRateLimiter
from app.core.config import Settings
from app.core.models import Base
from app.identity.models import AuthIdentity
from app.mcp_server.asgi import build_mcp_app
from app.mcp_server.auth import AuthKitTokenVerifier
from app.organizations.models import Membership
from tests.access_helpers import mint_key, seed_tenant

BASE, RESOURCE, ISSUER = "https://mcp.example.test", "https://mcp.example.test/mcp", "https://auth.example.test"
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
           "MCP-Protocol-Version": "2025-11-25"}


@pytest.fixture(scope="module")
def private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture()
def factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _make_client(factory, private_key, *, limit=60, static_keys=False):
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db", mcp_resource_url=RESOURCE, mcp_issuer_url=ISSUER,
                        mcp_allowed_hosts="mcp.example.test", mcp_rate_limit_per_minute=limit,
                        mcp_static_key_enabled=static_keys)
    verifier = AuthKitTokenVerifier(issuer=ISSUER, resource=RESOURCE, key_resolver=lambda _t: private_key.public_key())
    app = build_mcp_app(settings, factory, InMemoryRateLimiter(), verifier)
    return TestClient(app, base_url=BASE)


@pytest.fixture()
def client(factory, private_key):
    with _make_client(factory, private_key) as c:
        yield c


def _bind(factory, tenant, subject):
    with factory.begin() as session:
        session.add(AuthIdentity(user_id=tenant.user_id, provider="workos", provider_subject=subject,
                                 verified_email="x@example.test"))
        session.add(McpConnection(organization_id=tenant.organization_id, user_id=tenant.user_id))


def _token(private_key, subject, **overrides):
    claims = {"iss": ISSUER, "aud": RESOURCE, "sub": subject, "exp": int(time.time()) + 300, **overrides}
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": "k1"})


@pytest.fixture()
def world(factory, private_key):
    a, b = seed_tenant(factory, "A", "Projeto Aurora entrega em setembro"), seed_tenant(factory, "B", "Projeto Zenite")
    _bind(factory, a, "user_A")
    _bind(factory, b, "user_B")
    return a, b, _token(private_key, "user_A"), _token(private_key, "user_B")


def rpc_raw(client, token, method, params=None, rid=1):
    headers = dict(HEADERS) | ({"Authorization": f"Bearer {token}"} if token else {})
    return client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})


def rpc(client, token, method, params=None):
    response = rpc_raw(client, token, method, params)
    assert response.status_code == 200, response.text
    return response.json()


def call(client, token, name, arguments):
    return rpc(client, token, "tools/call", {"name": name, "arguments": arguments})


def test_unauthenticated_request_gets_401_with_resource_metadata(client):
    response = rpc_raw(client, None, "tools/list")
    assert response.status_code == 401
    assert ('resource_metadata="https://mcp.example.test/.well-known/oauth-protected-resource/mcp"'
            in response.headers["www-authenticate"])


def test_protected_resource_metadata_names_the_authorization_server(client):
    body = client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert body["resource"] == RESOURCE and body["authorization_servers"] == [ISSUER]
    assert body["bearer_methods_supported"] == ["header"]


def test_health_is_public(client):
    assert client.get("/health/live").status_code == 200


def test_only_three_read_only_tools_are_listed(client, world):
    _a, _b, token_a, _tb = world
    tools = rpc(client, token_a, "tools/list")["result"]["tools"]
    assert {t["name"] for t in tools} == {"search", "fetch", "list_sources"}
    assert all(t["annotations"]["readOnlyHint"] is True and t["annotations"]["openWorldHint"] is False
               and t["annotations"]["destructiveHint"] is False for t in tools)


def test_tokens_for_another_audience_expired_or_forged_are_401(client, world, private_key):
    for token in (_token(private_key, "user_A", aud="https://other.example.test/mcp"),
                  _token(private_key, "user_A", exp=int(time.time()) - 5), "garbage"):
        response = rpc_raw(client, token, "tools/list")
        assert response.status_code == 401 and "resource_metadata=" in response.headers["www-authenticate"]


def test_valid_token_without_binding_is_401(client, factory, private_key):
    seed_tenant(factory, "C", "x")
    assert rpc_raw(client, _token(private_key, "user_unknown"), "tools/list").status_code == 401


def test_search_result_is_structured_content_and_json_text(client, world):
    _a, _b, token_a, _tb = world
    result = call(client, token_a, "search", {"query": "Aurora"})["result"]
    assert result["isError"] is False and result["structuredContent"]["results"][0]["id"]
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]


def test_fetch_and_list_sources_work(client, world):
    a, _b, token_a, _tb = world
    doc = call(client, token_a, "fetch", {"id": str(a.document_id)})["result"]["structuredContent"]
    assert doc["metadata"]["content_trust"] == "untrusted_document_content"
    sources = call(client, token_a, "list_sources", {})["result"]["structuredContent"]["sources"]
    assert len(sources) == 1


def test_org_b_token_never_sees_org_a_documents(client, world):
    a, _b, _ta, token_b = world
    fetched = call(client, token_b, "fetch", {"id": str(a.document_id)})["result"]
    assert fetched["isError"] is True and "not found" in fetched["content"][0]["text"]
    searched = call(client, token_b, "search", {"query": "Aurora"})["result"]
    assert searched["structuredContent"]["results"] == []


def test_every_call_is_audited_without_content(client, world, factory):
    _a, _b, token_a, _tb = world
    call(client, token_a, "search", {"query": "Aurora"})
    with factory() as s:
        row = s.query(ApiAuditEvent).filter_by(channel="mcp", action="search").one()
    assert row.query_length == 6 and row.status == "ok" and row.result_count == 1
    assert "Aurora" not in repr(row.__dict__) and row.user_id is not None


def test_failed_fetch_is_audited_as_denied(client, world, factory):
    a, _b, _ta, token_b = world
    call(client, token_b, "fetch", {"id": str(a.document_id)})
    with factory() as s:
        assert s.query(ApiAuditEvent).filter_by(channel="mcp", action="fetch", status="denied").count() == 1


def test_rate_limit_applies_per_user(factory, private_key, world):
    _a, _b, token_a, token_b = world
    with _make_client(factory, private_key, limit=2) as limited:
        assert rpc_raw(limited, token_a, "tools/list").status_code == 200
        assert rpc_raw(limited, token_a, "tools/list").status_code == 200
        third = rpc_raw(limited, token_a, "tools/list")
        assert third.status_code == 429 and "retry-after" in third.headers
        assert rpc_raw(limited, token_b, "tools/list").status_code == 200  # other user unaffected


def test_revocation_and_member_deactivation_take_effect_on_the_next_call(client, world, factory):
    _a, _b, token_a, token_b = world
    assert rpc_raw(client, token_a, "tools/list").status_code == 200
    with factory.begin() as s:
        s.query(McpConnection).filter(McpConnection.user_id == world[0].user_id).update({"revoked_at": datetime.now(UTC)})
    assert rpc_raw(client, token_a, "tools/list").status_code == 401
    assert rpc_raw(client, token_b, "tools/list").status_code == 200
    with factory.begin() as s:
        s.query(Membership).filter(Membership.user_id == world[1].user_id).update({"is_active": False})
    assert rpc_raw(client, token_b, "tools/list").status_code == 401


def test_unexpected_host_is_rejected(client, world):
    _a, _b, token_a, _tb = world
    response = client.post("/mcp", headers=HEADERS | {"Authorization": f"Bearer {token_a}", "Host": "evil.example.test"},
                           json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 421


def test_plan_c_static_api_key_is_off_by_default(client, factory):
    a = seed_tenant(factory, "A", "Projeto Aurora")
    assert rpc_raw(client, mint_key(factory, a), "tools/list").status_code == 401


def test_plan_c_static_api_key_works_when_enabled_and_stays_scoped(factory, private_key):
    a, b = seed_tenant(factory, "A", "Projeto Aurora"), seed_tenant(factory, "B", "Projeto Zenite")
    key_a, revoked = mint_key(factory, a), mint_key(factory, a, revoked=True)
    only_search = mint_key(factory, b, scopes={"search:read"})
    with _make_client(factory, private_key, static_keys=True) as static:
        assert [t["name"] for t in rpc(static, key_a, "tools/list")["result"]["tools"]] == ["search", "fetch", "list_sources"]
        assert call(static, key_a, "search", {"query": "Aurora"})["result"]["structuredContent"]["results"]
        assert call(static, key_a, "search", {"query": "Zenite"})["result"]["structuredContent"]["results"] == []
        assert call(static, only_search, "fetch", {"id": str(b.document_id)})["result"]["isError"] is True
        assert rpc_raw(static, revoked, "tools/list").status_code == 401
        assert rpc_raw(static, "arq_nope_nothing", "tools/list").status_code == 401
    with factory() as s:
        assert s.query(ApiAuditEvent).filter_by(channel="mcp", action="search").count() == 2
