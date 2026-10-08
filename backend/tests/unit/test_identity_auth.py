import base64
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.identity.auth import (
    AuthenticationUnavailable,
    IdentityService,
    VerifiedIdentity,
    WorkOSAuthKitGateway,
    canonical_email,
    hash_secret,
    workos_session_id,
)
from app.identity.models import AuthIdentity, User, UserSession


class FakeSession:
    def __init__(self, *, scalar_results: list[object | None] | None = None, user: User | None = None) -> None:
        self.scalar_results = list(scalar_results or [])
        self.user = user
        self.added: list[object] = []
        self.flush_count = 0
        self.executed: list[object] = []

    def scalar(self, statement: object) -> object | None:
        return self.scalar_results.pop(0)

    def get(self, model: type[User], user_id: object) -> User | None:
        return self.user

    def add(self, instance: object) -> None:
        self.added.append(instance)

    def flush(self) -> None:
        self.flush_count += 1

    def execute(self, statement: object) -> None:
        self.executed.append(statement)


def test_canonical_email_and_hash_are_deterministic() -> None:
    assert canonical_email("  PERSON@Example.Test ") == "person@example.test"
    assert hash_secret("opaque-secret") == hash_secret("opaque-secret")
    assert len(hash_secret("opaque-secret")) == 64
    assert hash_secret("opaque-secret") != "opaque-secret"


def test_unconfigured_workos_gateway_fails_without_network() -> None:
    gateway = WorkOSAuthKitGateway(api_key=None, client_id=None, redirect_uri=None)

    with pytest.raises(AuthenticationUnavailable, match="not configured"):
        gateway.authorization_url(state="csrf-state")


def test_establish_identity_creates_canonical_user_and_identity() -> None:
    session = FakeSession(scalar_results=[None, None])
    identity = VerifiedIdentity(provider="workos", subject="user_123", email=" Person@Example.Test ")

    user = IdentityService(session).establish_identity(identity)

    assert isinstance(user, User)
    assert user.email == "person@example.test"
    assert len(session.added) == 2
    stored_identity = session.added[1]
    assert isinstance(stored_identity, AuthIdentity)
    assert stored_identity.user_id == user.id
    assert stored_identity.provider == "workos"
    assert stored_identity.provider_subject == "user_123"
    assert stored_identity.verified_email == "person@example.test"


def test_establish_identity_is_idempotent_for_provider_subject() -> None:
    user = User(id=uuid4(), email="person@example.test")
    existing_identity = AuthIdentity(
        id=uuid4(), user_id=user.id, provider="workos", provider_subject="user_123", verified_email=user.email
    )
    session = FakeSession(scalar_results=[existing_identity], user=user)

    returned_user = IdentityService(session).establish_identity(
        VerifiedIdentity(provider="workos", subject="user_123", email="changed@example.test")
    )

    assert returned_user is user
    assert session.added == []


def test_establish_identity_rejects_orphaned_external_identity() -> None:
    existing_identity = AuthIdentity(
        id=uuid4(), user_id=uuid4(), provider="workos", provider_subject="user_123", verified_email="person@test"
    )
    session = FakeSession(scalar_results=[existing_identity], user=None)

    with pytest.raises(AuthenticationUnavailable, match="has no user"):
        IdentityService(session).establish_identity(
            VerifiedIdentity(provider="workos", subject="user_123", email="person@test")
        )


def test_created_session_persists_only_hash_and_sets_future_expiration() -> None:
    session = FakeSession()
    before = datetime.now(UTC)

    stored_session, raw_secret = IdentityService(session).create_session(
        user_id=uuid4(), ttl_hours=24, provider_session_id="session_01HXYZ"
    )

    assert isinstance(stored_session, UserSession)
    assert raw_secret
    assert stored_session.secret_hash == hash_secret(raw_secret)
    assert stored_session.secret_hash != raw_secret
    assert stored_session.provider_session_id == "session_01HXYZ"
    assert stored_session.expires_at > before
    assert session.added == [stored_session]


@pytest.mark.parametrize("raw_secret", [None, "altered-secret"])
def test_missing_or_altered_session_secret_authenticates_no_user(raw_secret: str | None) -> None:
    session = FakeSession(scalar_results=[None])

    assert IdentityService(session).authenticated_user(raw_secret) is None


def test_revoking_a_session_never_persists_raw_secret() -> None:
    stored_session = UserSession(
        user_id=uuid4(),
        secret_hash=hash_secret("opaque-secret"),
        provider_session_id="session_01HXYZ",
        expires_at=datetime.now(UTC),
    )
    session = FakeSession(scalar_results=[stored_session])

    provider_session_id = IdentityService(session).revoke_session("opaque-secret")

    assert provider_session_id == "session_01HXYZ"
    assert stored_session.revoked_at is not None
    assert session.executed == []


def test_workos_session_id_reads_only_a_well_formed_session_claim() -> None:
    payload = base64.urlsafe_b64encode(json.dumps({"sid": "session_01HXYZ"}).encode()).decode().rstrip("=")

    assert workos_session_id(f"header.{payload}.signature") == "session_01HXYZ"
    assert workos_session_id("header.invalid.signature") is None
    assert workos_session_id(None) is None


@pytest.mark.parametrize("operation", ["authenticate_password"])
def test_password_gateway_uses_workos_sdk_and_verified_subject(monkeypatch, operation):
    from types import SimpleNamespace
    gateway = WorkOSAuthKitGateway(api_key="test", client_id="client_test", redirect_uri="http://callback.test")
    calls = []
    response = SimpleNamespace(user=SimpleNamespace(id="user_123", email="person@example.test", email_verified=True), access_token=None)
    resource = SimpleNamespace(
        create_user=lambda **kwargs: calls.append(kwargs),
        authenticate_with_password=lambda **kwargs: response,
    )
    monkeypatch.setattr(gateway, "_client", lambda: SimpleNamespace(user_management=resource))
    identity = getattr(gateway, operation)(email="Person@example.test", password="test-password", ip_address="127.0.0.1", user_agent="test")
    assert identity.subject == "user_123"



@pytest.mark.parametrize("code,expected", [("email_verification_required", "PendingEmailVerification"), ("mfa_challenge", "HostedAuthenticationRequired"), ("sso_required", "HostedAuthenticationRequired")])
def test_password_gateway_handles_provider_challenges(monkeypatch, code, expected):
    from types import SimpleNamespace

    from workos._errors import AuthorizationError
    gateway = WorkOSAuthKitGateway(api_key="test", client_id="client_test", redirect_uri="http://callback.test")
    def authenticate(**kwargs):
        raise AuthorizationError(response_json={"code": code, "pending_authentication_token": "secret"})
    monkeypatch.setattr(gateway, "_client", lambda: SimpleNamespace(user_management=SimpleNamespace(authenticate_with_password=authenticate)))
    result = gateway.authenticate_password(email="person@example.test", password="test-password", ip_address=None, user_agent=None)
    assert type(result).__name__ == expected


def test_password_gateway_rejects_unverified_identity(monkeypatch):
    from types import SimpleNamespace
    gateway = WorkOSAuthKitGateway(api_key="test", client_id="client_test", redirect_uri="http://callback.test")
    response = SimpleNamespace(user=SimpleNamespace(id="user_123", email="person@example.test", email_verified=False))
    monkeypatch.setattr(gateway, "_client", lambda: SimpleNamespace(user_management=SimpleNamespace(authenticate_with_password=lambda **kwargs: response)))
    with pytest.raises(AuthenticationUnavailable):
        gateway.authenticate_password(email="person@example.test", password="test-password", ip_address=None, user_agent=None)


def test_password_gateway_does_not_leak_sdk_errors(monkeypatch):
    from types import SimpleNamespace

    from workos._errors import BadRequestError

    from app.identity.auth import AuthenticationRejected
    gateway = WorkOSAuthKitGateway(api_key="test", client_id="client_test", redirect_uri="http://callback.test")
    def authenticate(**kwargs):
        raise BadRequestError(response_json={"message": "secret provider details", "password": "test-password"})
    monkeypatch.setattr(gateway, "_client", lambda: SimpleNamespace(user_management=SimpleNamespace(authenticate_with_password=authenticate)))
    with pytest.raises(AuthenticationRejected) as error:
        gateway.authenticate_password(email="person@example.test", password="test-password", ip_address=None, user_agent=None)
    assert "secret" not in str(error.value)
    assert "test-password" not in str(error.value)


def test_registration_stores_no_password_and_requests_ownership_link(monkeypatch):
    from types import SimpleNamespace
    gateway = WorkOSAuthKitGateway(api_key="test", client_id="client", redirect_uri="http://callback.test")
    calls = []
    resource = SimpleNamespace(list_users=lambda **kw: SimpleNamespace(data=[]), create_user=lambda **kw: calls.append(("create", kw)), reset_password=lambda **kw: calls.append(("reset", kw)))
    monkeypatch.setattr(gateway, "_client", lambda: SimpleNamespace(user_management=resource))
    gateway.register_account(email=" Person@Example.Test ", ip_address="198.51.100.10", user_agent="test")
    assert calls == [("create", {"email": "person@example.test", "ip_address": "198.51.100.10", "user_agent": "test"}), ("reset", {"email": "person@example.test"})]


def test_existing_registration_returns_same_result_without_overwriting_credentials(monkeypatch):
    from types import SimpleNamespace
    gateway = WorkOSAuthKitGateway(api_key="test", client_id="client", redirect_uri="http://callback.test")
    calls = []
    resource = SimpleNamespace(list_users=lambda **kw: SimpleNamespace(data=[SimpleNamespace(id="existing")]), create_user=lambda **kw: pytest.fail("must not recreate"), reset_password=lambda **kw: calls.append(kw))
    monkeypatch.setattr(gateway, "_client", lambda: SimpleNamespace(user_management=resource))
    assert gateway.register_account(email="existing@example.test", ip_address=None, user_agent=None) is None
    assert calls == [{"email": "existing@example.test"}]


@pytest.mark.parametrize("operation,kwargs", [
    ("authenticate_password", {"email": "person@example.test", "password": "test", "ip_address": None, "user_agent": None}),
    ("verify_email", {"token": "secret", "code": "123456", "ip_address": None, "user_agent": None}),
    ("register_account", {"email": "person@example.test", "ip_address": None, "user_agent": None}),
    ("request_password_reset", {"email": "person@example.test"}),
    ("confirm_password_reset", {"token": "secret", "password": "test-password"}),
])
def test_workos_429_is_rate_limited_without_provider_details(monkeypatch, operation, kwargs):
    from types import SimpleNamespace

    from workos._errors import RateLimitExceededError

    from app.identity.auth import AuthenticationRateLimited
    gateway = WorkOSAuthKitGateway(api_key="test", client_id="client", redirect_uri="http://callback.test")
    def limited(*args, **kw):
        raise RateLimitExceededError(response_json={"message": "private provider secret"})
    resource = SimpleNamespace(authenticate_with_password=limited, authenticate_with_email_verification=limited, list_users=limited, reset_password=limited, confirm_password_reset=limited)
    monkeypatch.setattr(gateway, "_client", lambda: SimpleNamespace(user_management=resource))
    with pytest.raises(AuthenticationRateLimited) as error:
        getattr(gateway, operation)(**kwargs)
    assert "private" not in str(error.value)


def test_workos_retry_after_is_preserved(monkeypatch):
    from types import SimpleNamespace

    from workos._errors import RateLimitExceededError

    from app.identity.auth import AuthenticationRateLimited
    gateway = WorkOSAuthKitGateway(api_key="test", client_id="client", redirect_uri="http://callback.test")
    def limited(**kw): raise RateLimitExceededError(response_json={}, retry_after=120)
    monkeypatch.setattr(gateway, "_client", lambda: SimpleNamespace(user_management=SimpleNamespace(authenticate_with_password=limited)))
    with pytest.raises(AuthenticationRateLimited) as error:
        gateway.authenticate_password(email="person@example.test", password="test", ip_address=None, user_agent=None)
    assert error.value.retry_after == 120
