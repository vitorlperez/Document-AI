import time
from datetime import UTC, datetime

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.access.models import McpConnection, OrganizationAccessSettings
from app.core.models import Base
from app.identity.models import AuthIdentity
from app.mcp_server.auth import AuthKitTokenVerifier, InvalidToken, McpPrincipalResolver
from app.organizations.models import Membership
from tests.access_helpers import seed_tenant

RESOURCE, ISSUER = "https://mcp.example.test/mcp", "https://auth.example.test"


@pytest.fixture(scope="module")
def keypair():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private, private.public_key()


def _token(private, **overrides):
    claims = {"iss": ISSUER, "aud": RESOURCE, "sub": "user_01ABC", "exp": int(time.time()) + 300, **overrides}
    return jwt.encode(claims, private, algorithm="RS256", headers={"kid": "k1"})


def _verifier(public):
    return AuthKitTokenVerifier(issuer=ISSUER, resource=RESOURCE, key_resolver=lambda token: public)


def test_valid_token_yields_the_workos_subject(keypair):
    private, public = keypair
    verified = _verifier(public).verify(_token(private, scope="a b", client_id="cli"))
    assert verified.subject == "user_01ABC" and verified.scopes == ["a", "b"] and verified.client_id == "cli"


@pytest.mark.parametrize("override", [
    {"aud": "https://other.example.test/mcp"},
    {"iss": "https://evil.example.test"},
    {"exp": int(time.time()) - 10},
])
def test_wrong_audience_issuer_or_expiry_is_rejected(keypair, override):
    private, public = keypair
    with pytest.raises(InvalidToken):
        _verifier(public).verify(_token(private, **override))


def test_missing_audience_is_rejected(keypair):
    private, public = keypair
    token = jwt.encode({"iss": ISSUER, "sub": "u", "exp": int(time.time()) + 60}, private, algorithm="RS256")
    with pytest.raises(InvalidToken):
        _verifier(public).verify(token)


def test_audience_list_containing_the_resource_is_accepted(keypair):
    private, public = keypair
    assert _verifier(public).verify(_token(private, aud=[RESOURCE, "x"])).subject == "user_01ABC"


def test_alg_none_and_hs256_are_rejected(keypair):
    _private, public = keypair
    forged = jwt.encode({"iss": ISSUER, "aud": RESOURCE, "sub": "u", "exp": int(time.time()) + 60}, "k" * 32, algorithm="HS256")
    none = jwt.encode({"iss": ISSUER, "aud": RESOURCE, "sub": "u", "exp": int(time.time()) + 60}, None, algorithm="none")
    for token in (forged, none, "garbage"):
        with pytest.raises(InvalidToken):
            _verifier(public).verify(token)


def test_key_resolver_failure_is_an_invalid_token(keypair):
    private, _public = keypair

    def boom(token):
        raise RuntimeError("jwks down")

    with pytest.raises(InvalidToken):
        AuthKitTokenVerifier(issuer=ISSUER, resource=RESOURCE, key_resolver=boom).verify(_token(private))


@pytest.fixture()
def factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _link(factory, tenant, subject="user_01ABC", *, connect=True, node_ids=None):
    with factory.begin() as session:
        session.add(AuthIdentity(user_id=tenant.user_id, provider="workos", provider_subject=subject, verified_email="a@example.test"))
        if connect:
            session.add(McpConnection(organization_id=tenant.organization_id, user_id=tenant.user_id, node_ids=node_ids))


def test_resolver_builds_an_mcp_principal_from_the_binding(factory):
    a = seed_tenant(factory, "A", "x")
    _link(factory, a)
    with factory() as session:
        principal = McpPrincipalResolver(session).resolve("user_01ABC")
    assert (principal.organization_id, principal.user_id, principal.channel) == (a.organization_id, a.user_id, "mcp")
    assert principal.scopes == frozenset({"search:read", "documents:read"}) and principal.node_ids is None


def test_resolver_carries_node_restriction(factory):
    from uuid import uuid4
    a, node = seed_tenant(factory, "A", "x"), uuid4()
    _link(factory, a, node_ids=[str(node)])
    with factory() as session:
        assert McpPrincipalResolver(session).resolve("user_01ABC").node_ids == (node,)


@pytest.mark.parametrize("break_it", ["unknown_subject", "no_binding", "revoked", "mcp_disabled", "not_member"])
def test_resolver_fails_closed_uniformly(factory, break_it):
    a = seed_tenant(factory, "A", "x")
    _link(factory, a, connect=break_it != "no_binding")
    with factory.begin() as session:
        if break_it == "revoked":
            session.query(McpConnection).update({"revoked_at": datetime.now(UTC)})
        if break_it == "mcp_disabled":
            session.get(OrganizationAccessSettings, a.organization_id).mcp_enabled = False
        if break_it == "not_member":
            session.query(Membership).update({"is_active": False})
    with factory() as session, pytest.raises(InvalidToken):
        McpPrincipalResolver(session).resolve("someone_else" if break_it == "unknown_subject" else "user_01ABC")
