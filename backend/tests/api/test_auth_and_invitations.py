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

    def authorization_url(self, *, state: str) -> str:
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
