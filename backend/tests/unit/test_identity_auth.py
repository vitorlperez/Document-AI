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
