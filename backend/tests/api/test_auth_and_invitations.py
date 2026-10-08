import importlib
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.access.ratelimit import InMemoryRateLimiter
from app.audit_usage.models import AuditLog
from app.core.config import Settings
from app.core.models import Base
from app.identity.auth import AuthenticationUnavailable, VerifiedIdentity
from app.identity.models import AuthIdentity, User, UserSession
from app.organizations.models import Membership, MembershipInvitation, MembershipRole, Organization


class FakeAuthGateway:
    def __init__(self) -> None:
        self.identities: dict[str, VerifiedIdentity] = {}
        self.codes: list[str] = []

    def authorization_url(self, *, state: str, screen_hint: str | None = None, max_age: int | None = None) -> str:
        return f"https://auth.example.test/login?state={state}"

    def exchange_code(self, *, code: str) -> VerifiedIdentity:
        self.codes.append(code)
        try:
            return self.identities[code]
        except KeyError as error:
            raise AuthenticationUnavailable("invalid code") from error


class FakeInvitationDelivery:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def send(self, *, recipient: str, invitation_url: str) -> None:
        self.messages.append({"recipient": recipient, "invitation_url": invitation_url})


@pytest.fixture()
def auth_api(monkeypatch) -> Generator[tuple[TestClient, sessionmaker[Session], FakeAuthGateway, FakeInvitationDelivery]]:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db")
    main = importlib.import_module("app.main")
    settings = Settings(
        database_url="postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db",
        public_app_url="http://app.example.test",
        environment="development",
    )
    app = main.create_app(settings)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    gateway = FakeAuthGateway()
    delivery = FakeInvitationDelivery()
    app.state.session_factory = factory
    app.state.auth_gateway = gateway
    app.state.rate_limiter = InMemoryRateLimiter()
    app.state.invitation_delivery = delivery
    with TestClient(app) as client:
        yield client, factory, gateway, delivery
    Base.metadata.drop_all(engine)
    engine.dispose()


def callback(client: TestClient, gateway: FakeAuthGateway, *, code: str, email: str, subject: str) -> str:
    gateway.identities[code] = VerifiedIdentity(provider="workos", subject=subject, email=email)
    login_response = client.get("/auth/login", follow_redirects=False)
    assert login_response.status_code == 302
    state = parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]
    assert state
    assert client.cookies.get("document_intelligence_login_state") == state
    response = client.get(f"/auth/callback?code={code}&state={state}", follow_redirects=False)
    assert response.status_code == 302
    cookie = client.cookies.get("document_intelligence_session")
    assert cookie
    return cookie


def test_callback_rejects_missing_or_mismatched_login_state(auth_api) -> None:
    client, factory, gateway, _ = auth_api
    gateway.identities["good"] = VerifiedIdentity(provider="workos", subject="subject", email="person@example.test")

    missing_without_login = client.get("/auth/callback?code=good", follow_redirects=False)
    client.get("/auth/login", follow_redirects=False)
    missing_after_login = client.get("/auth/callback?code=good", follow_redirects=False)
    client.get("/auth/login", follow_redirects=False)
    mismatched = client.get("/auth/callback?code=good&state=wrong-state", follow_redirects=False)

    assert missing_without_login.status_code == 401
    assert missing_after_login.status_code == 401
    assert missing_after_login.json() == {"detail": "authentication failed"}
    assert mismatched.status_code == 401
    assert mismatched.json() == {"detail": "authentication failed"}
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 0
        assert session.scalar(select(func.count()).select_from(UserSession)) == 0


def test_login_returns_only_to_a_valid_invitation_path(auth_api) -> None:
    client, _, gateway, _ = auth_api
    token = "a" * 43
    gateway.identities["invited"] = VerifiedIdentity(provider="workos", subject="invitee", email="invitee@example.test")

    started = client.get(f"/auth/login?return_to=/invitations/{token}", follow_redirects=False)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    completed = client.get(f"/auth/callback?code=invited&state={state}", follow_redirects=False)

    assert completed.status_code == 302
    assert completed.headers["location"] == f"http://app.example.test/invitations/{token}"
    assert client.cookies.get("document_intelligence_return_to") is None


@pytest.mark.parametrize("return_to", ["https://attacker.example.test", "//attacker.example.test", "/companies/not-an-invitation"])
def test_login_rejects_forged_return_paths(auth_api, return_to: str) -> None:
    client, _, gateway, _ = auth_api
    gateway.identities["login"] = VerifiedIdentity(provider="workos", subject="person", email="person@example.test")

    started = client.get("/auth/login", params={"return_to": return_to}, follow_redirects=False)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    completed = client.get(f"/auth/callback?code=login&state={state}", follow_redirects=False)

    assert completed.status_code == 302
    assert completed.headers["location"] == "http://app.example.test"


def invitation_token(delivery: FakeInvitationDelivery) -> str:
    assert len(delivery.messages) == 1
    return urlparse(delivery.messages[0]["invitation_url"]).path.rsplit("/", 1)[1]


def make_membership(
    factory: sessionmaker[Session], *, organization_id, user_id, role: MembershipRole
) -> Membership:
    with factory.begin() as session:
        membership = Membership(
            organization_id=organization_id, user_id=user_id, role=role, is_active=True
        )
        session.add(membership)
    return membership


def test_callback_is_idempotent_and_issues_hash_only_opaque_sessions(auth_api) -> None:
    client, factory, gateway, _ = auth_api
    first_raw_session = callback(
        client, gateway, code="first", email=" Person@Example.Test ", subject="workos-user-1"
    )
    second_raw_session = callback(
        client, gateway, code="second", email="person@example.test", subject="workos-user-1"
    )

    assert first_raw_session != second_raw_session
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1
        assert session.scalar(select(func.count()).select_from(AuthIdentity)) == 1
        sessions = list(session.scalars(select(UserSession)))
        assert len(sessions) == 2
        assert {stored.secret_hash for stored in sessions} == {
            sha256(first_raw_session.encode()).hexdigest(),
            sha256(second_raw_session.encode()).hexdigest(),
        }
        assert all(first_raw_session != stored.secret_hash for stored in sessions)
        assert all(second_raw_session != stored.secret_hash for stored in sessions)


def test_same_verified_email_with_different_subjects_creates_distinct_users(auth_api) -> None:
    client, factory, gateway, _ = auth_api
    callback(client, gateway, code="first", email="person@example.test", subject="workos-user-1")
    first_user_id = client.get("/me").json()["id"]
    callback(client, gateway, code="second", email="person@example.test", subject="workos-user-2")
    second_user_id = client.get("/me").json()["id"]

    assert first_user_id != second_user_id
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 2
        assert session.scalar(select(func.count()).select_from(AuthIdentity)) == 2
        assert session.scalar(select(func.count()).select_from(UserSession)) == 2


@pytest.mark.parametrize("cookie", [None, "altered-session"])
def test_me_rejects_missing_or_altered_session_without_details(auth_api, cookie: str | None) -> None:
    client, _, _, _ = auth_api
    if cookie is not None:
        client.cookies.set("document_intelligence_session", cookie)

    response = client.get("/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "authentication required"}
    assert "session" not in response.text.lower()


@pytest.mark.parametrize("state", ["expired", "revoked"])
def test_me_rejects_expired_or_revoked_session(auth_api, state: str) -> None:
    client, factory, gateway, _ = auth_api
    raw_session = callback(client, gateway, code="login", email="person@example.test", subject="subject-1")
    with factory.begin() as session:
        stored = session.scalar(select(UserSession).where(UserSession.secret_hash == sha256(raw_session.encode()).hexdigest()))
        assert stored is not None
        if state == "expired":
            stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        else:
            stored.revoked_at = datetime.now(UTC)

    response = client.get("/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "authentication required"}


def test_authenticated_user_creates_organization_owner_and_audit(auth_api) -> None:
    client, factory, gateway, _ = auth_api
    callback(client, gateway, code="login", email="owner@example.test", subject="owner")

    response = client.post("/organizations", json={"name": "Acme"})

    assert response.status_code == 201
    assert response.json()["role"] == "owner"
    with factory() as session:
        membership = session.scalar(select(Membership))
        audit = session.scalar(select(AuditLog).where(AuditLog.action == "membership.created"))
        assert membership is not None
        assert membership.role is MembershipRole.OWNER
        assert audit is not None
        assert audit.organization_id == membership.organization_id
        assert audit.target_id == membership.id


def test_owner_invitation_delivers_raw_token_once_and_persists_hash_only(auth_api) -> None:
    client, factory, gateway, delivery = auth_api
    callback(client, gateway, code="owner-login", email="owner@example.test", subject="owner")
    organization_id = client.post("/organizations", json={"name": "Acme"}).json()["id"]

    response = client.post(
        f"/organizations/{organization_id}/members/invitations",
        json={"email": "Invitee@acme.co", "role": "admin"},
    )

    assert response.status_code == 202
    assert response.json() == {"status": "sent"}
    token = invitation_token(delivery)
    assert delivery.messages[0]["recipient"] == "invitee@acme.co"
    with factory() as session:
        invitation = session.scalar(select(MembershipInvitation))
        assert invitation is not None
        assert invitation.email == "invitee@acme.co"
        assert invitation.role is MembershipRole.ADMIN
        assert invitation.token_hash == sha256(token.encode()).hexdigest()
        assert token != invitation.token_hash
        audit = session.scalar(select(AuditLog).where(AuditLog.action == "invitation.created"))
        assert audit is not None
        assert audit.target_id == invitation.id


@pytest.mark.parametrize("role", [MembershipRole.ADMIN, MembershipRole.MEMBER])
def test_non_owner_cannot_invite_or_change_organization_state(auth_api, role: MembershipRole) -> None:
    client, factory, gateway, delivery = auth_api
    callback(client, gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    callback(client, gateway, code="non-owner", email=f"{role.value}@example.test", subject=role.value)
    with factory() as session:
        user = session.scalar(select(User).where(User.email == f"{role.value}@example.test"))
        assert user is not None
        make_membership(factory, organization_id=UUID(organization_id), user_id=user.id, role=role)

    response = client.post(
        f"/organizations/{organization_id}/members/invitations",
        json={"email": "invitee@acme.co", "role": "member"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "not allowed"}
    assert delivery.messages == []
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(MembershipInvitation)) == 0
        assert session.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "invitation.created")) == 0


def test_invitation_acceptance_requires_matching_verified_email_and_is_single_use(auth_api) -> None:
    client, factory, gateway, delivery = auth_api
    callback(client, gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    client.post(
        f"/organizations/{organization_id}/members/invitations",
        json={"email": "invitee@acme.co", "role": "member"},
    )
    token = invitation_token(delivery)

    callback(client, gateway, code="wrong", email="wrong@example.test", subject="wrong")
    mismatch = client.post(f"/invitations/{token}/accept")
    assert mismatch.status_code == 404
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(Membership).where(Membership.role == MembershipRole.MEMBER)) == 0

    callback(client, gateway, code="invitee", email="invitee@acme.co", subject="invitee")
    accepted = client.post(f"/invitations/{token}/accept")
    repeated = client.post(f"/invitations/{token}/accept")

    assert accepted.status_code == 201
    assert accepted.json() == {"organization_id": organization_id, "role": "member"}
    assert repeated.status_code == 404
    with factory() as session:
        invitation = session.scalar(select(MembershipInvitation))
        assert invitation is not None and invitation.accepted_at is not None
        assert session.scalar(select(func.count()).select_from(Membership).where(Membership.role == MembershipRole.MEMBER)) == 1


def test_expired_revoked_or_altered_token_cannot_be_accepted(auth_api) -> None:
    client, factory, gateway, delivery = auth_api
    callback(client, gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    request = lambda email: client.post(
        f"/organizations/{organization_id}/members/invitations", json={"email": email, "role": "member"}
    )
    request("invitee@acme.co")
    token = invitation_token(delivery)
    callback(client, gateway, code="invitee", email="invitee@acme.co", subject="invitee")

    assert client.post("/invitations/altered-token/accept").status_code == 404
    with factory.begin() as session:
        invitation = session.scalar(
            select(MembershipInvitation).where(MembershipInvitation.token_hash == sha256(token.encode()).hexdigest())
        )
        assert invitation is not None
        invitation.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert client.post(f"/invitations/{token}/accept").status_code == 404
    with factory() as session:
        invitation = session.scalar(select(MembershipInvitation).order_by(MembershipInvitation.created_at.desc()))
        assert invitation is not None
        invitation.revoked_at = datetime.now(UTC)
        session.commit()
    assert client.post(f"/invitations/{token}/accept").status_code == 404


def test_owner_cannot_create_invitation_in_another_organization(auth_api) -> None:
    client, factory, gateway, delivery = auth_api
    callback(client, gateway, code="owner-a", email="owner-a@example.test", subject="owner-a")
    organization_a = client.post("/organizations", json={"name": "A"}).json()["id"]
    callback(client, gateway, code="owner-b", email="owner-b@example.test", subject="owner-b")
    organization_b = client.post("/organizations", json={"name": "B"}).json()["id"]
    callback(client, gateway, code="owner-a-again", email="owner-a@example.test", subject="owner-a")

    response = client.post(
        f"/organizations/{organization_b}/members/invitations",
        json={"email": "invitee@acme.co", "role": "member"},
    )

    assert response.status_code == 403
    assert delivery.messages == []
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(MembershipInvitation)) == 0
        assert session.scalar(select(Organization).where(Organization.id == UUID(organization_a))) is not None


def test_company_listing_and_member_management_are_owner_scoped(auth_api) -> None:
    client, factory, gateway, _ = auth_api
    callback(client, gateway, code="owner", email="owner@example.test", subject="owner")
    organization_a = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    organization_b = client.post("/organizations", json={"name": "Beta"}).json()["id"]
    callback(client, gateway, code="member", email="member@example.test", subject="member")
    with factory() as session:
        member = session.scalar(select(User).where(User.email == "member@example.test"))
        assert member is not None
    membership = make_membership(factory, organization_id=UUID(organization_a), user_id=member.id, role=MembershipRole.MEMBER)

    assert client.get("/organizations").json() == [{"id": organization_a, "name": "Acme", "membership_id": str(membership.id), "role": "member"}]
    assert client.get(f"/organizations/{organization_a}/members").status_code == 403
    callback(client, gateway, code="owner-again", email="owner@example.test", subject="owner")
    listed = client.get(f"/organizations/{organization_a}/members")
    changed = client.patch(f"/organizations/{organization_a}/members/{membership.id}", json={"role": "admin"})
    wrong_company = client.patch(f"/organizations/{organization_b}/members/{membership.id}", json={"role": "member"})

    assert listed.status_code == 200 and {row["email"] for row in listed.json()} == {"owner@example.test", "member@example.test"}
    assert changed.json() == {"id": str(membership.id), "role": "admin"}
    assert wrong_company.status_code == 404
    with factory() as session:
        assert session.scalar(select(AuditLog).where(AuditLog.action == "membership.role_changed")) is not None


def password_gateway(monkeypatch, gateway, result):
    calls = []

    def authenticate(**kwargs):
        calls.append(kwargs)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(gateway, "authenticate_password", authenticate, raising=False)
    monkeypatch.setattr(gateway, "register_password", authenticate, raising=False)
    monkeypatch.setattr(gateway, "verify_email", authenticate, raising=False)
    return calls


@pytest.mark.parametrize("path", ["/auth/password"])
def test_custom_login_creates_opaque_session_and_preserves_invitation(auth_api, monkeypatch, path):
    client, factory, gateway, _ = auth_api
    calls = password_gateway(monkeypatch, gateway, VerifiedIdentity(provider="workos", subject="user_custom", email="custom@example.com", provider_session_id="session_custom"))
    invitation = "/invitations/" + "a" * 43
    response = client.post(path, json={"email": "custom@example.com", "password": "long-password", "return_to": invitation})
    assert response.status_code == 200
    assert response.json() == {"status": "authenticated", "redirect_url": "http://app.example.test" + invitation}
    assert response.headers["cache-control"] == "no-store"
    assert "HttpOnly" in response.headers["set-cookie"]
    assert calls[0]["password"] == "long-password"
    raw = client.cookies.get("document_intelligence_session")
    assert client.get("/me").json()["email"] == "custom@example.com"
    with factory() as session:
        stored = session.scalar(select(UserSession))
        assert stored.secret_hash == sha256(raw.encode()).hexdigest()
        assert stored.provider_session_id == "session_custom"
        assert stored.secret_hash != raw


def test_custom_login_never_returns_provider_token_or_creates_unverified_user(auth_api, monkeypatch):
    from app.identity.auth import PendingEmailVerification
    client, factory, gateway, _ = auth_api
    password_gateway(monkeypatch, gateway, PendingEmailVerification(token="provider-pending-secret"))
    response = client.post("/auth/password", json={"email": "pending@example.com", "password": "long-password"})
    assert response.json() == {"status": "email_verification_required"}
    assert "provider-pending-secret" not in response.text
    assert "HttpOnly" in response.headers["set-cookie"]
    assert client.cookies.get("document_intelligence_session") is None
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 0
    password_gateway(monkeypatch, gateway, VerifiedIdentity(provider="workos", subject="user_verified", email="pending@example.com"))
    completed = client.post("/auth/verify-email", json={"code": "123456"})
    assert completed.json()["status"] == "authenticated"
    assert client.cookies.get("document_intelligence_pending_verification") is None


def test_verification_rejects_missing_pending_cookie(auth_api, monkeypatch):
    client, _, gateway, _ = auth_api
    calls = password_gateway(monkeypatch, gateway, None)
    assert client.post("/auth/verify-email", json={"code": "123456"}).status_code == 400
    assert calls == []


def test_custom_login_keeps_advanced_challenges_on_hosted_authkit(auth_api, monkeypatch):
    from app.identity.auth import HostedAuthenticationRequired
    client, factory, gateway, _ = auth_api
    password_gateway(monkeypatch, gateway, HostedAuthenticationRequired())
    response = client.post("/auth/password", json={"email": "mfa@example.com", "password": "long-password"})
    assert response.json() == {"status": "hosted_authentication_required"}
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(UserSession)) == 0


@pytest.mark.parametrize("error,expected", [(AuthenticationUnavailable("private provider data"), 503)])
def test_custom_login_masks_provider_outage(auth_api, monkeypatch, error, expected):
    client, _, gateway, _ = auth_api
    password_gateway(monkeypatch, gateway, error)
    response = client.post("/auth/password", json={"email": "person@example.com", "password": "long-password"})
    assert response.status_code == expected
    assert "private provider data" not in response.text


def test_custom_login_checks_origin_before_creating_anonymous_session(auth_api, monkeypatch):
    client, _, gateway, _ = auth_api
    calls = password_gateway(monkeypatch, gateway, None)
    response = client.post("/auth/password", headers={"Origin": "https://attacker.test"}, json={"email": "person@example.com", "password": "long-password"})
    assert response.status_code == 403
    assert calls == []
    client.app.state.settings.environment = "production"
    assert client.post("/auth/password", json={"email": "person@example.com", "password": "long-password"}).status_code == 403


def test_custom_login_rate_limits_by_email_before_calling_workos(auth_api, monkeypatch):
    from app.identity.auth import AuthenticationRejected
    client, _, gateway, _ = auth_api
    calls = password_gateway(monkeypatch, gateway, AuthenticationRejected("invalid credentials"))
    for _ in range(10):
        assert client.post("/auth/password", json={"email": "person@example.com", "password": "long-password"}).status_code == 400
    limited = client.post("/auth/password", json={"email": "person@example.com", "password": "long-password"})
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) > 0
    assert len(calls) == 10


def test_custom_login_rejects_external_return_url(auth_api, monkeypatch):
    client, _, gateway, _ = auth_api
    password_gateway(monkeypatch, gateway, VerifiedIdentity(provider="workos", subject="user_safe", email="safe@example.com"))
    response = client.post("/auth/password", json={"email": "safe@example.com", "password": "long-password", "return_to": "https://attacker.test"})
    assert response.json()["redirect_url"] == "http://app.example.test"


def test_password_reset_revokes_all_local_sessions_without_provider_retry_or_login_block(auth_api, monkeypatch):
    client, factory, gateway, _ = auth_api
    subject = "user_reset"
    old_secrets = [callback(client, gateway, code=f"reset-{i}", email="person@example.com", subject=subject) for i in range(4)]
    unrelated_secret = callback(client, gateway, code="unrelated", email="other@example.com", subject="user_other")
    with factory.begin() as session:
        rows = list(session.scalars(select(UserSession).join(AuthIdentity, AuthIdentity.user_id == UserSession.user_id).where(AuthIdentity.provider_subject == subject)))
        rows[0].expires_at = datetime.now(UTC) - timedelta(hours=1)
        rows[1].revoked_at = datetime.now(UTC) - timedelta(hours=2)
        previously_revoked = rows[1].revoked_at.replace(tzinfo=None)
    monkeypatch.setattr(gateway, "confirm_password_reset", lambda **kwargs: subject, raising=False)
    def redundant_provider_call(**kwargs):
        pytest.fail("WorkOS reset already revokes provider sessions; no separate revocation call")
    monkeypatch.setattr(gateway, "revoke_user_sessions", redundant_provider_call, raising=False)
    client.cookies.clear()
    client.cookies.set("document_intelligence_session", old_secrets[2], domain="testserver.local")
    response = client.post("/auth/password-reset/confirm", json={"token": "reset-token", "password": "new-long-password"})
    assert response.status_code == 200
    assert response.json() == {"status": "password_reset"}
    assert client.cookies.get("document_intelligence_session") is None
    with factory() as session:
        rows = list(session.scalars(select(UserSession).join(AuthIdentity, AuthIdentity.user_id == UserSession.user_id).where(AuthIdentity.provider_subject == subject)))
        assert len(rows) == 4
        assert all(row.revoked_at is not None for row in rows)
        assert any(row.revoked_at.replace(tzinfo=None) == previously_revoked for row in rows)
    for secret in old_secrets:
        client.cookies.clear()
        client.cookies.set("document_intelligence_session", secret)
        assert client.get("/me").status_code == 401
    client.cookies.clear()
    client.cookies.set("document_intelligence_session", unrelated_secret)
    assert client.get("/me").status_code == 200
    client.cookies.clear()
    password_gateway(monkeypatch, gateway, VerifiedIdentity(provider="workos", subject=subject, email="person@example.com"))
    assert client.post("/auth/password", json={"email": "person@example.com", "password": "new-long-password"}).status_code == 200
    assert client.get("/me").status_code == 200
    fresh_hosted = callback(client, gateway, code="after-reset", email="person@example.com", subject=subject)
    assert fresh_hosted not in old_secrets
    assert client.get("/me").status_code == 200


def test_password_reset_request_returns_only_generic_status(auth_api, monkeypatch):
    client, _, gateway, _ = auth_api
    monkeypatch.setattr(gateway, "request_password_reset", lambda **kwargs: None, raising=False)
    assert client.post("/auth/password-reset", json={"email": "unknown@example.com"}).json() == {"status": "sent"}


def test_auth_validation_errors_do_not_echo_submitted_secrets(auth_api):
    client, _, _, _ = auth_api
    response = client.post("/auth/password-reset/confirm", json={"token": {"secret": "sensitive-reset-token"}, "password": "sensitive-password"})
    assert response.status_code == 422
    assert response.json() == {"detail": "Confira os dados informados e tente novamente."}
    assert "sensitive" not in response.text
    assert response.headers["cache-control"] == "no-store"


def _signed_proxy_headers(ip, *, path="/auth/password", timestamp=None):
    import hmac
    import time
    secret = "test-only-proxy-secret-at-least-32-chars"
    timestamp = str(int(time.time()) if timestamp is None else timestamp)
    signature = hmac.new(secret.encode(), f"{timestamp}\nPOST\n{path}\n{ip}".encode(), "sha256").hexdigest()
    return {"x-auth-client-ip": ip, "x-auth-ip-timestamp": timestamp, "x-auth-ip-signature": signature}


def _configure_signed_proxy(client):
    from pydantic import SecretStr
    client.app.state.settings.auth_proxy_secret = SecretStr("test-only-proxy-secret-at-least-32-chars")
    client.app.state.settings.auth_trusted_proxy_cidrs = "127.0.0.1/32"


def test_two_clients_behind_proxy_have_separate_ip_buckets_and_workos_context(auth_api, monkeypatch):
    from app.identity.auth import AuthenticationRejected
    client, _, gateway, _ = auth_api
    _configure_signed_proxy(client)
    calls = password_gateway(monkeypatch, gateway, AuthenticationRejected("invalid"))
    with TestClient(client.app, client=("127.0.0.1", 12345)) as proxy:
        for i in range(60):
            response = proxy.post("/auth/password", headers=_signed_proxy_headers("198.51.100.10"), json={"email": f"person{i}@example.com", "password": "test"})
            assert response.status_code == 400
        assert proxy.post("/auth/password", headers=_signed_proxy_headers("198.51.100.10"), json={"email": "blocked@example.com", "password": "test"}).status_code == 429
        assert proxy.post("/auth/password", headers=_signed_proxy_headers("198.51.100.20"), json={"email": "other@example.com", "password": "test"}).status_code == 400
    assert calls[0]["ip_address"] == "198.51.100.10"
    assert calls[-1]["ip_address"] == "198.51.100.20"


@pytest.mark.parametrize("attack", ["untrusted_peer", "forged_signature", "expired", "wrong_path", "invalid_ip"])
def test_proxy_context_forgery_is_rejected_before_workos(auth_api, monkeypatch, attack):
    client, _, gateway, _ = auth_api
    _configure_signed_proxy(client)
    calls = password_gateway(monkeypatch, gateway, None)
    headers = _signed_proxy_headers("198.51.100.10")
    peer = "127.0.0.1"
    if attack == "untrusted_peer": peer = "203.0.113.10"
    if attack == "forged_signature": headers["x-auth-ip-signature"] = "0" * 64
    if attack == "expired": headers = _signed_proxy_headers("198.51.100.10", timestamp=1)
    if attack == "wrong_path": headers = _signed_proxy_headers("198.51.100.10", path="/auth/register")
    if attack == "invalid_ip": headers = _signed_proxy_headers("198.51.100.10, 203.0.113.10")
    with TestClient(client.app, client=(peer, 12345)) as proxy:
        response = proxy.post("/auth/password", headers=headers, json={"email": "person@example.com", "password": "test"})
    assert response.status_code == 403
    assert calls == []


def test_direct_client_cannot_change_ip_bucket_with_forwarded_headers(auth_api, monkeypatch):
    from app.identity.auth import AuthenticationRejected
    client, _, gateway, _ = auth_api
    calls = password_gateway(monkeypatch, gateway, AuthenticationRejected("invalid"))
    with TestClient(client.app, client=("198.51.100.10", 12345)) as direct:
        response = direct.post("/auth/password", headers={"x-forwarded-for": "203.0.113.66", "x-real-ip": "203.0.113.66", **_signed_proxy_headers("203.0.113.66")}, json={"email": "person@example.com", "password": "test"})
    assert response.status_code == 400
    assert calls[0]["ip_address"] == "198.51.100.10"


def test_verification_is_limited_by_pending_token_across_client_ips(auth_api, monkeypatch):
    from app.identity.auth import AuthenticationRejected
    client, _, gateway, _ = auth_api
    _configure_signed_proxy(client)
    calls = password_gateway(monkeypatch, gateway, AuthenticationRejected("invalid code"))
    path = "/auth/verify-email"
    with TestClient(client.app, client=("127.0.0.1", 12345)) as proxy:
        proxy.cookies.set("document_intelligence_pending_verification", "opaque-pending-token")
        for i in range(5):
            assert proxy.post(path, headers=_signed_proxy_headers(f"198.51.100.{i+1}", path=path), json={"code": "123456"}).status_code == 400
        assert proxy.post(path, headers=_signed_proxy_headers("198.51.100.20", path=path), json={"code": "123456"}).status_code == 429
    assert len(calls) == 5
    assert all("opaque-pending-token" not in key[0] for key in client.app.state.rate_limiter._counts)


def test_registration_never_sets_an_attacker_password_or_creates_session(auth_api, monkeypatch):
    client, factory, gateway, _ = auth_api
    calls = []
    monkeypatch.setattr(gateway, "register_account", lambda **kw: calls.append(kw), raising=False)
    response = client.post("/auth/register", json={"email": "victim@example.com", "password": "attacker-known-password"})
    assert response.json() == {"status": "registration_pending"}
    assert "password" not in calls[0]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(UserSession)) == 0


def test_password_reset_without_local_identity_needs_no_provider_revocation(auth_api, monkeypatch):
    client, factory, gateway, _ = auth_api
    monkeypatch.setattr(gateway, "confirm_password_reset", lambda **kw: "user_not_local", raising=False)
    monkeypatch.setattr(gateway, "revoke_user_sessions", lambda **kw: pytest.fail("redundant provider revocation"), raising=False)
    response = client.post("/auth/password-reset/confirm", json={"token": "reset-token", "password": "new-long-password"})
    assert response.status_code == 200
    assert response.json() == {"status": "password_reset"}
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(UserSession)) == 0


def test_resend_is_bound_to_authenticated_pending_context_and_throttled(auth_api, monkeypatch):
    from app.identity.auth import PendingEmailVerification
    client, _, gateway, _ = auth_api
    password_gateway(monkeypatch, gateway, PendingEmailVerification(token="pending-secret", verification_id="email_verification_123"))
    calls = []
    monkeypatch.setattr(gateway, "resend_verification", lambda **kw: calls.append(kw), raising=False)
    client.post("/auth/password", json={"email": "person@example.com", "password": "test"})
    context = client.cookies.get("document_intelligence_verification_context")
    assert context
    response = client.post("/auth/verify-email/resend")
    assert response.json() == {"status": "sent"}
    assert calls == [{"verification_id": "email_verification_123"}]
    assert client.post("/auth/verify-email/resend").status_code == 429
    client.cookies.clear()
    client.cookies.set("document_intelligence_pending_verification", "different-token")
    client.cookies.set("document_intelligence_verification_context", context)
    assert client.post("/auth/verify-email/resend").status_code == 400
    assert len(calls) == 1


def test_provider_rate_limit_returns_retry_after(auth_api, monkeypatch):
    from app.identity.auth import AuthenticationRateLimited
    client, _, gateway, _ = auth_api
    calls = password_gateway(monkeypatch, gateway, AuthenticationRateLimited("private"))
    response = client.post("/auth/password", json={"email": "person@example.com", "password": "test"})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
    assert "private" not in response.text
    assert len(calls) == 1



def test_registration_invitation_survives_reset_and_hosted_fallback(auth_api, monkeypatch):
    client, _, gateway, _ = auth_api
    invitation = "/invitations/" + "b" * 43
    monkeypatch.setattr(gateway, "register_account", lambda **kw: None, raising=False)
    monkeypatch.setattr(gateway, "confirm_password_reset", lambda **kw: "user_invited", raising=False)
    registered = client.post("/auth/register", json={"email": "invited@example.com", "return_to": invitation})
    assert registered.json() == {"status": "registration_pending"}
    reset = client.post("/auth/password-reset/confirm", json={"token": "test-reset", "password": "long-password"})
    assert reset.json()["return_to"] == invitation
    hosted = client.get("/auth/login", params={"return_to": reset.json()["return_to"]}, follow_redirects=False)
    assert hosted.status_code == 302
    gateway.identities["invited-after-reset"] = VerifiedIdentity(provider="workos", subject="user_invited", email="invited@example.com")
    state = parse_qs(urlparse(hosted.headers["location"]).query)["state"][0]
    completed = client.get("/auth/callback", params={"code": "invited-after-reset", "state": state}, follow_redirects=False)
    assert completed.headers["location"] == "http://app.example.test" + invitation


def test_production_custom_login_requires_trust_configuration(auth_api, monkeypatch):
    client, _, gateway, _ = auth_api
    client.app.state.settings.environment = "production"
    calls = password_gateway(monkeypatch, gateway, None)
    response = client.post("/auth/password", headers={"origin": "http://app.example.test"}, json={"email": "person@example.com", "password": "test"})
    assert response.status_code == 503
    assert calls == []
