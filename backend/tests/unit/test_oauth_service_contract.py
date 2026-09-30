"""Behaviour every OAuth connection service must share (Google Drive, OneDrive, Notion)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.audit_usage.models import AuditLog
from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.identity.auth import hash_secret
from app.identity.models import User, UserSession
from app.integrations.google_drive import (
    CredentialCipher,
    GoogleAccessDenied,
    GoogleConnectionService,
    GoogleCredentials,
    GoogleOAuthInvalid,
)
from app.integrations.models import DataSource, OAuthConnectionState
from app.integrations.notion import NotionAccessDenied, NotionConnectionService, NotionOAuthInvalid
from app.integrations.onedrive import (
    OneDriveAccessDenied,
    OneDriveCipher,
    OneDriveConnectionService,
    OneDriveCredentials,
    OneDriveOAuthInvalid,
)
from app.library import models as library_models  # noqa: F401
from app.organizations.models import Membership, MembershipRole, Organization

KEY = Fernet.generate_key().decode()


class GoogleLikePort:
    def authorization_url(self, *, state: str, scope: str = "") -> str:
        return f"https://idp.example.test/auth?state={state}"

    def exchange_code(self, *, code: str) -> GoogleCredentials:
        return GoogleCredentials("plain-access-token", "plain-refresh-token", None)

    def account_email(self, *, credentials: object) -> str | None:
        return "owner@example.test"


class GraphPort(GoogleLikePort):
    def exchange_code(self, *, code: str) -> OneDriveCredentials:
        return OneDriveCredentials(
            "plain-access-token", "plain-refresh-token", datetime.now(UTC) + timedelta(hours=1)
        )

    def drive_id(self, *, credentials: object) -> str:
        return "drive-1"


@dataclass
class Harness:
    provider: str
    service: object
    denied: type[Exception]
    invalid: type[Exception]
    begin: Callable[[OrganizationScope, UUID, str], str]
    complete: Callable[[str, str], DataSource]
    disconnect: Callable[[OrganizationScope, UUID, UUID], DataSource]


def build(provider: str, session: Session) -> Harness:
    if provider == "google_drive":
        port, service = GoogleLikePort(), GoogleConnectionService(session, CredentialCipher(KEY))
        return Harness(
            provider,
            service,
            GoogleAccessDenied,
            GoogleOAuthInvalid,
            lambda scope, uid, sec: service.begin(
                scope=scope, user_id=uid, session_secret=sec, port=port
            ),
            lambda raw, sec: service.complete(
                raw_state=raw, code="code", session_secret=sec, port=port
            ),
            lambda scope, uid, sid: service.disconnect(scope=scope, user_id=uid, source_id=sid),
        )
    if provider == "onedrive":
        service = OneDriveConnectionService(session, OneDriveCipher(KEY), GraphPort())
    else:
        service = NotionConnectionService(session, CredentialCipher(KEY), GoogleLikePort())
    denied, invalid = (
        (OneDriveAccessDenied, OneDriveOAuthInvalid)
        if provider == "onedrive"
        else (NotionAccessDenied, NotionOAuthInvalid)
    )
    return Harness(
        provider,
        service,
        denied,
        invalid,
        lambda scope, uid, sec: service.begin(scope=scope, user_id=uid, session_secret=sec),
        lambda raw, sec: service.complete(raw_state=raw, code="code", session_secret=sec),
        lambda scope, uid, sid: service.disconnect(scope=scope, user_id=uid, source_id=sid),
    )


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    Base.metadata.drop_all(engine)
    engine.dispose()


def seed(db: Session, role: MembershipRole) -> tuple[OrganizationScope, UUID]:
    organization, user = Organization(name="Acme"), User(email=f"u-{uuid4()}@example.test")
    db.add_all([organization, user])
    db.flush()
    db.add(Membership(organization_id=organization.id, user_id=user.id, role=role, is_active=True))
    db.add(
        UserSession(
            user_id=user.id,
            secret_hash=hash_secret("session"),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    db.flush()
    return OrganizationScope(organization.id), user.id


def raw_state(url: str) -> str:
    return url.split("state=", 1)[1]


PROVIDERS = ["google_drive", "onedrive", "notion"]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_member_cannot_begin_a_connection(session: Session, provider: str) -> None:
    scope, user_id = seed(session, MembershipRole.MEMBER)
    with pytest.raises(build(provider, session).denied):
        build(provider, session).begin(scope, user_id, "session")


@pytest.mark.parametrize("provider", PROVIDERS)
def test_complete_stores_only_ciphertext_and_consumes_the_state(
    session: Session, provider: str
) -> None:
    scope, user_id = seed(session, MembershipRole.ADMIN)
    harness = build(provider, session)
    raw = raw_state(harness.begin(scope, user_id, "session"))

    source = harness.complete(raw, "session")

    assert source.provider == provider and source.status == "connected"
    assert source.encrypted_credentials and "plain-access-token" not in source.encrypted_credentials
    state = session.scalar(
        select(OAuthConnectionState).where(OAuthConnectionState.state_hash == hash_secret(raw))
    )
    assert state is not None and state.consumed_at is not None


@pytest.mark.parametrize("provider", PROVIDERS)
def test_state_cannot_be_replayed_expired_or_used_from_another_session(
    session: Session, provider: str
) -> None:
    scope, user_id = seed(session, MembershipRole.ADMIN)
    harness = build(provider, session)
    first = raw_state(harness.begin(scope, user_id, "session"))
    harness.complete(first, "session")
    with pytest.raises(harness.invalid):
        harness.complete(first, "session")  # replay

    second = raw_state(harness.begin(scope, user_id, "session"))
    with pytest.raises(harness.invalid):
        harness.complete(second, "another-session")

    third = raw_state(harness.begin(scope, user_id, "session"))
    state = session.scalar(
        select(OAuthConnectionState).where(OAuthConnectionState.state_hash == hash_secret(third))
    )
    state.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.flush()
    with pytest.raises(harness.invalid):
        harness.complete(third, "session")


@pytest.mark.parametrize(
    "provider",
    [
        "google_drive",
        "onedrive",
        "notion",
    ],
)
def test_disconnect_clears_credentials_invalidates_pending_states_and_audits(
    session: Session, provider: str
) -> None:
    scope, user_id = seed(session, MembershipRole.ADMIN)
    harness = build(provider, session)
    source = harness.complete(raw_state(harness.begin(scope, user_id, "session")), "session")
    pending = raw_state(harness.begin(scope, user_id, "session"))
    pending_row = session.scalar(
        select(OAuthConnectionState).where(OAuthConnectionState.state_hash == hash_secret(pending))
    )
    pending_row.source_id = source.id
    session.flush()

    harness.disconnect(scope, user_id, source.id)

    assert source.encrypted_credentials is None and source.status == "disconnected"
    assert pending_row.consumed_at is not None
    assert session.scalar(
        select(AuditLog).where(
            AuditLog.action == "data_source.disconnected", AuditLog.target_id == source.id
        )
    )
