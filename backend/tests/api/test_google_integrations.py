import importlib
from collections.abc import Generator
from datetime import UTC, datetime
from hashlib import sha256
from urllib.parse import parse_qs, urlencode, urlparse
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.models import Base
from app.identity.auth import AuthenticationUnavailable, VerifiedIdentity
from app.identity.models import User, UserSession
from app.integrations.google_drive import (
    GOOGLE_DRIVE_READONLY_SCOPE,
    GoogleCredentials,
    GoogleRemoteUnauthorized,
    RemoteFolder,
)
from app.integrations.models import DataSource, OAuthConnectionState
from app.knowledge.models import Document
from app.library.models import LibraryNode
from app.organizations.models import Membership, MembershipRole
from app.workspaces.models import WorkspaceFolder, WorkspaceFolderSelection


class FakeAuthGateway:
    def __init__(self) -> None:
        self.identities: dict[str, VerifiedIdentity] = {}
        self.authorization_calls: list[dict[str, object]] = []
        self.logout_calls: list[dict[str, str]] = []

    def authorization_url(
        self, *, state: str, screen_hint: str | None = None, max_age: int | None = None
    ) -> str:
        self.authorization_calls.append({"state": state, "screen_hint": screen_hint, "max_age": max_age})
        return f"https://auth.example.test/login?{urlencode({'state': state})}"

    def exchange_code(self, *, code: str) -> VerifiedIdentity:
        try:
            return self.identities[code]
        except KeyError as error:
            raise AuthenticationUnavailable("invalid code") from error

    def logout_url(self, *, session_id: str, return_to: str) -> str:
        self.logout_calls.append({"session_id": session_id, "return_to": return_to})
        return f"https://auth.example.test/logout?{urlencode({'sid': session_id, 'return_to': return_to})}"


class FakeGooglePort:
    def __init__(self) -> None:
        self.authorization_calls: list[dict[str, str]] = []
        self.exchange_calls: list[str] = []
        self.credentials = GoogleCredentials("google-access-token", "google-refresh-token", None)
        self.authorized_email = "drive-owner@example.test"
        self.account_calls: list[GoogleCredentials] = []
        self.folders = [RemoteFolder("folder-1", "Client A")]
        self.raise_unauthorized = False

    def authorization_url(self, *, state: str, scope: str) -> str:
        self.authorization_calls.append({"state": state, "scope": scope})
        return f"https://google.example.test/oauth?state={state}"

    def exchange_code(self, *, code: str) -> GoogleCredentials:
        self.exchange_calls.append(code)
        return self.credentials

    def account_email(self, *, credentials: GoogleCredentials) -> str | None:
        self.account_calls.append(credentials)
        return self.authorized_email

    def list_folders(self, *, credentials: GoogleCredentials) -> list[RemoteFolder]:
        if self.raise_unauthorized:
            raise GoogleRemoteUnauthorized("remote token must never reach the response")
        return self.folders


@pytest.fixture()
def google_api(monkeypatch) -> Generator[tuple[TestClient, sessionmaker[Session], FakeAuthGateway, FakeGooglePort]]:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db")
    main = importlib.import_module("app.main")
    settings = Settings(
        database_url="postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db",
        public_app_url="http://app.example.test",
        environment="development",
        google_token_encryption_key=Fernet.generate_key().decode(),
    )
    app = main.create_app(settings)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    auth_gateway, google_port = FakeAuthGateway(), FakeGooglePort()
    app.state.session_factory = factory
    app.state.auth_gateway = auth_gateway
    app.state.google_drive_port = google_port
    with TestClient(app) as client:
        yield client, factory, auth_gateway, google_port
    Base.metadata.drop_all(engine)
    engine.dispose()


def login(
    client: TestClient,
    gateway: FakeAuthGateway,
    *,
    code: str,
    email: str,
    subject: str,
    provider_session_id: str | None = None,
) -> None:
    gateway.identities[code] = VerifiedIdentity(
        provider="workos", subject=subject, email=email, provider_session_id=provider_session_id
    )
    start = client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    response = client.get(f"/auth/callback?code={code}&state={state}", follow_redirects=False)
    assert response.status_code == 302


def create_organization(client: TestClient) -> UUID:
    response = client.post("/organizations", json={"name": "Acme"})
    assert response.status_code == 201
    return UUID(response.json()["id"])


def test_authkit_login_uses_the_selected_screen_hint(google_api) -> None:
    client, _, auth_gateway, _ = google_api

    response = client.get("/auth/login?screen_hint=sign-up", follow_redirects=False)

    assert response.status_code == 302
    assert auth_gateway.authorization_calls[-1]["screen_hint"] == "sign-up"
    assert auth_gateway.authorization_calls[-1]["max_age"] is None
    assert client.get("/auth/login?screen_hint=unexpected", follow_redirects=False).status_code == 422


def test_logout_ends_the_remote_authkit_session_and_revokes_the_local_session(google_api) -> None:
    client, _, auth_gateway, _ = google_api
    login(
        client,
        auth_gateway,
        code="owner",
        email="owner@example.test",
        subject="owner",
        provider_session_id="session_01HXYZ",
    )

    response = client.post("/auth/logout")

    assert response.status_code == 200
    assert response.json()["redirect_url"].startswith("https://auth.example.test/logout?")
    assert auth_gateway.logout_calls == [
        {"session_id": "session_01HXYZ", "return_to": "http://app.example.test"}
    ]
    assert client.get("/me").status_code == 401


def test_legacy_logout_forces_a_fresh_authentication_challenge(google_api) -> None:
    client, _, auth_gateway, _ = google_api
    login(client, auth_gateway, code="owner", email="owner@example.test", subject="owner")

    response = client.post("/auth/logout")
    next_login = client.get("/auth/login?screen_hint=sign-in", follow_redirects=False)

    assert response.json()["redirect_url"] == "http://app.example.test"
    assert auth_gateway.logout_calls == []
    assert next_login.status_code == 302
    assert auth_gateway.authorization_calls[-1]["screen_hint"] == "sign-in"
    assert auth_gateway.authorization_calls[-1]["max_age"] == 0


def test_google_oauth_callback_is_one_time_hashes_state_and_encrypts_credentials(google_api) -> None:
    client, factory, auth_gateway, google_port = google_api
    login(client, auth_gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)

    start = client.post("/data-sources/google/oauth/start", json={"organization_id": str(organization_id)}, follow_redirects=False)
    assert start.status_code == 302
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    assert google_port.authorization_calls == [{"state": state, "scope": GOOGLE_DRIVE_READONLY_SCOPE}]
    with factory() as session:
        oauth_state = session.scalar(select(OAuthConnectionState))
        assert oauth_state is not None
        assert oauth_state.organization_id == organization_id
        assert oauth_state.state_hash == sha256(state.encode()).hexdigest()
        assert state not in oauth_state.state_hash

    completed = client.get(f"/data-sources/google/oauth/callback?code=google-code&state={state}")
    replayed = client.get(f"/data-sources/google/oauth/callback?code=google-code&state={state}")

    assert completed.status_code == 200
    assert completed.json()["status"] == "connected"
    assert replayed.status_code == 401
    assert google_port.exchange_calls == ["google-code"]
    assert google_port.account_calls == [google_port.credentials]
    with factory() as session:
        source = session.scalar(select(DataSource))
        assert source is not None
        assert source.organization_id == organization_id
        assert source.encrypted_credentials != google_port.credentials.access_token
        assert google_port.credentials.access_token not in source.encrypted_credentials
        assert source.account_email == "drive-owner@example.test"


def test_google_oauth_browser_callback_redirects_to_the_state_bound_integration_screen(google_api) -> None:
    client, _, auth_gateway, _ = google_api
    login(client, auth_gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    started = client.post(
        "/data-sources/google/oauth/start",
        json={"organization_id": str(organization_id)},
        follow_redirects=False,
    )
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]

    completed = client.get(
        f"/data-sources/google/oauth/callback?code=google-code&state={state}",
        headers={"accept": "text/html,application/xhtml+xml"},
        follow_redirects=False,
    )

    assert completed.status_code == 303
    assert completed.headers["location"] == (
        f"http://app.example.test/companies/{organization_id}/integrations?connected=google_drive"
    )
    assert "google-code" not in completed.headers["location"]
    assert state not in completed.headers["location"]


def test_google_oauth_start_accepts_top_level_browser_navigation(google_api) -> None:
    client, _, auth_gateway, google_port = google_api
    login(client, auth_gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)

    start = client.get(
        f"/data-sources/google/oauth/start?organization_id={organization_id}", follow_redirects=False
    )

    assert start.status_code == 302
    assert start.headers["location"].startswith("https://google.example.test/oauth?state=")
    assert google_port.authorization_calls[0]["scope"] == GOOGLE_DRIVE_READONLY_SCOPE


@pytest.mark.parametrize("state", ["missing", "mismatched"])
def test_invalid_google_state_does_not_exchange_code_or_create_source(google_api, state: str) -> None:
    client, factory, auth_gateway, google_port = google_api
    login(client, auth_gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    if state == "mismatched":
        client.post("/data-sources/google/oauth/start", json={"organization_id": str(organization_id)})
    response = client.get(f"/data-sources/google/oauth/callback?code=google-code&state={state}")

    assert response.status_code == 401
    assert response.json() == {"detail": "authentication failed"}
    assert google_port.exchange_calls == []
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(DataSource)) == 0


def test_callback_rejects_oauth_state_when_initiating_server_session_is_no_longer_active(google_api) -> None:
    client, factory, auth_gateway, google_port = google_api
    login(client, auth_gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    started = client.post(
        "/data-sources/google/oauth/start",
        json={"organization_id": str(organization_id)},
        follow_redirects=False,
    )
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    with factory.begin() as session:
        server_session = session.scalar(select(UserSession))
        assert server_session is not None
        server_session.revoked_at = datetime.now(UTC)

    response = client.get(f"/data-sources/google/oauth/callback?code=google-code&state={state}")

    assert response.status_code == 401
    assert response.json() == {"detail": "authentication failed"}
    assert google_port.exchange_calls == []
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(DataSource)) == 0


def test_member_and_cross_tenant_user_cannot_manage_sources(google_api) -> None:
    client, factory, auth_gateway, _ = google_api
    login(client, auth_gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    started = client.post(
        "/data-sources/google/oauth/start", json={"organization_id": str(organization_id)}, follow_redirects=False
    )
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    source_id = client.get(f"/data-sources/google/oauth/callback?code=code&state={state}").json()["id"]
    login(client, auth_gateway, code="member", email="member@example.test", subject="member")
    with factory.begin() as session:
        member = session.scalar(select(User).where(User.email == "member@example.test"))
        assert member is not None
        session.add(Membership(organization_id=organization_id, user_id=member.id, role=MembershipRole.MEMBER, is_active=True))
    member_list = client.get(f"/data-sources?organization_id={organization_id}")
    member_start = client.post("/data-sources/google/oauth/start", json={"organization_id": str(organization_id)})
    member_disconnect = client.delete(f"/data-sources/{source_id}?organization_id={organization_id}")

    login(client, auth_gateway, code="outsider", email="outsider@example.test", subject="outsider")
    outsider_list = client.get(f"/data-sources?organization_id={organization_id}")
    outsider_disconnect = client.delete(f"/data-sources/{source_id}?organization_id={organization_id}")

    assert member_list.status_code == 403
    assert member_start.status_code == 403
    assert member_disconnect.status_code == 403
    assert outsider_list.status_code == 403
    assert outsider_disconnect.status_code == 403
    with factory() as session:
        source = session.get(DataSource, UUID(source_id))
        assert source is not None and source.status == "connected" and source.encrypted_credentials is not None


def test_source_list_and_folder_selection_are_tenant_scoped_and_require_confirmation(google_api) -> None:
    client, factory, auth_gateway, _ = google_api
    login(client, auth_gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    start = client.post("/data-sources/google/oauth/start", json={"organization_id": str(organization_id)}, follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    source_id = UUID(client.get(f"/data-sources/google/oauth/callback?code=code&state={state}").json()["id"])

    sources = client.get(f"/data-sources?organization_id={organization_id}")
    unconfirmed = client.post(
        f"/workspace-folders?organization_id={organization_id}",
        json={"source_id": str(source_id), "external_folder_id": "folder-1", "name": "Client A", "uniform_access_confirmed": False},
    )
    selected = client.post(
        f"/workspace-folders?organization_id={organization_id}",
        json={"source_id": str(source_id), "external_folder_id": "folder-1", "name": "Client A", "uniform_access_confirmed": True},
    )
    duplicate = client.post(
        f"/workspace-folders?organization_id={organization_id}",
        json={"source_id": str(source_id), "external_folder_id": "folder-1", "name": "Changed", "uniform_access_confirmed": True},
    )

    assert sources.status_code == 200
    assert sources.json() == [{"id": str(source_id), "provider": "google_drive", "status": "connected", "account_email": "drive-owner@example.test"}]
    assert "credentials" not in sources.text
    assert unconfirmed.status_code == 422
    assert selected.status_code == 201
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == selected.json()["id"]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(WorkspaceFolder)) == 1


def test_reauthorization_reuses_source_uuid_and_refreshes_authorized_account(google_api) -> None:
    client, factory, auth_gateway, google_port = google_api
    login(client, auth_gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    first = client.post("/data-sources/google/oauth/start", json={"organization_id": str(organization_id)}, follow_redirects=False)
    first_state = parse_qs(urlparse(first.headers["location"]).query)["state"][0]
    source_id = client.get(f"/data-sources/google/oauth/callback?code=first&state={first_state}").json()["id"]
    google_port.credentials = GoogleCredentials("replacement-access", "replacement-refresh", None)
    google_port.authorized_email = "replacement@example.test"

    reauthorization = client.get(
        f"/data-sources/google/oauth/start?organization_id={organization_id}&source_id={source_id}",
        follow_redirects=False,
    )
    reauthorization_state = parse_qs(urlparse(reauthorization.headers["location"]).query)["state"][0]
    completed = client.get(f"/data-sources/google/oauth/callback?code=replacement&state={reauthorization_state}")

    assert completed.json() == {"id": source_id, "status": "connected"}
    with factory() as session:
        sources = list(session.scalars(select(DataSource)))
        assert len(sources) == 1
        assert sources[0].account_email == "replacement@example.test"
        assert sources[0].encrypted_credentials is not None
        assert "replacement-access" not in sources[0].encrypted_credentials


def test_disconnect_clears_connection_and_preserves_existing_knowledge(google_api) -> None:
    client, factory, auth_gateway, _ = google_api
    login(client, auth_gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    started = client.post("/data-sources/google/oauth/start", json={"organization_id": str(organization_id)}, follow_redirects=False)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    source_id = UUID(client.get(f"/data-sources/google/oauth/callback?code=code&state={state}").json()["id"])
    with factory.begin() as session:
        folder = WorkspaceFolder(
            organization_id=organization_id,
            source_id=source_id,
            external_folder_id="folder-1",
            name="Client A",
            uniform_access_confirmed=True,
        )
        session.add(folder)
        session.flush()
        session.add(
            Document(
                organization_id=organization_id,
                workspace_folder_id=folder.id,
                external_file_id="document-1",
                name="Briefing",
                mime_type="application/pdf",
                source_url="https://drive.example.test/document-1",
                content_hash="a" * 64,
                processing_version="v1",
                index_status="indexed",
            )
        )
        session.add(
            LibraryNode(
                organization_id=organization_id,
                source_id=source_id,
                parent_id=None,
                external_id="source-root",
                kind="source",
                name="Google Drive",
                mime_type=None,
                source_url=None,
            )
        )

    disconnected = client.delete(f"/data-sources/{source_id}?organization_id={organization_id}")
    listed = client.get(f"/data-sources?organization_id={organization_id}")
    catalog = client.get(f"/data-sources/{source_id}/scope-catalog?organization_id={organization_id}")

    assert disconnected.status_code == 204
    assert listed.json() == [{"id": str(source_id), "provider": "google_drive", "status": "disconnected", "account_email": None}]
    assert catalog.status_code == 403
    with factory() as session:
        source = session.get(DataSource, source_id)
        assert source is not None and source.encrypted_credentials is None and source.account_email is None
        assert source.status == "disconnected"
        assert session.scalar(select(func.count()).select_from(WorkspaceFolder)) == 1
        assert session.scalar(select(func.count()).select_from(Document)) == 1
        assert session.scalar(select(func.count()).select_from(LibraryNode)) == 1


def test_disconnect_invalidates_pending_reauthorization(google_api) -> None:
    client, factory, auth_gateway, _ = google_api
    login(client, auth_gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    initial = client.post("/data-sources/google/oauth/start", json={"organization_id": str(organization_id)}, follow_redirects=False)
    initial_state = parse_qs(urlparse(initial.headers["location"]).query)["state"][0]
    source_id = client.get(f"/data-sources/google/oauth/callback?code=initial&state={initial_state}").json()["id"]
    reauthorization = client.get(
        f"/data-sources/google/oauth/start?organization_id={organization_id}&source_id={source_id}", follow_redirects=False
    )
    pending_state = parse_qs(urlparse(reauthorization.headers["location"]).query)["state"][0]

    assert client.delete(f"/data-sources/{source_id}?organization_id={organization_id}").status_code == 204
    assert client.get(f"/data-sources/google/oauth/callback?code=late&state={pending_state}").status_code == 401
    with factory() as session:
        source = session.get(DataSource, UUID(source_id))
        assert source is not None and source.status == "disconnected"


def test_workspace_folder_must_be_enumerated_by_the_connected_google_source(google_api) -> None:
    client, factory, auth_gateway, _ = google_api
    login(client, auth_gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    started = client.post("/data-sources/google/oauth/start", json={"organization_id": str(organization_id)}, follow_redirects=False)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    source_id = client.get(f"/data-sources/google/oauth/callback?code=code&state={state}").json()["id"]

    response = client.post(
        f"/workspace-folders?organization_id={organization_id}",
        json={"source_id": source_id, "external_folder_id": "folder-not-enumerated", "name": "Forged", "uniform_access_confirmed": True},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "folder is not available from this source"}
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(WorkspaceFolder)) == 0


def test_admin_lists_remote_folders_only_for_own_connected_source(google_api) -> None:
    client, _, auth_gateway, google_port = google_api
    login(client, auth_gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    start = client.post("/data-sources/google/oauth/start", json={"organization_id": str(organization_id)}, follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    source_id = client.get(f"/data-sources/google/oauth/callback?code=code&state={state}").json()["id"]

    response = client.get(f"/data-sources/{source_id}/folders?organization_id={organization_id}")

    assert response.status_code == 200
    assert response.json() == [{"id": "folder-1", "name": "Client A"}]
    assert "google-access-token" not in response.text
    assert google_port.folders == [RemoteFolder("folder-1", "Client A")]


def test_google_unauthorized_marks_source_reauth_required_without_secret_leakage(google_api) -> None:
    client, factory, auth_gateway, google_port = google_api
    login(client, auth_gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    start = client.post("/data-sources/google/oauth/start", json={"organization_id": str(organization_id)}, follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    source_id = client.get(f"/data-sources/google/oauth/callback?code=code&state={state}").json()["id"]
    google_port.raise_unauthorized = True

    response = client.get(f"/data-sources/{source_id}/folders?organization_id={organization_id}")

    assert response.status_code == 409
    assert response.json() == {"detail": "reauthentication required"}
    assert "google-access-token" not in response.text
    assert "remote token" not in response.text
    with factory() as session:
        source = session.get(DataSource, UUID(source_id))
        assert source is not None
        assert source.status == "reauth_required"


def test_cross_tenant_source_cannot_be_selected_as_workspace_folder(google_api) -> None:
    client, _, auth_gateway, _ = google_api
    login(client, auth_gateway, code="owner-a", email="owner-a@example.test", subject="owner-a")
    organization_a = create_organization(client)
    start = client.post("/data-sources/google/oauth/start", json={"organization_id": str(organization_a)}, follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    source_id = client.get(f"/data-sources/google/oauth/callback?code=code&state={state}").json()["id"]
    login(client, auth_gateway, code="owner-b", email="owner-b@example.test", subject="owner-b")
    organization_b = create_organization(client)

    response = client.post(
        f"/workspace-folders?organization_id={organization_b}",
        json={"source_id": source_id, "external_folder_id": "folder-1", "name": "Client A", "uniform_access_confirmed": True},
    )

    assert response.status_code == 403


def test_admin_creates_one_workspace_scope_from_multiple_folders_and_root_files(google_api) -> None:
    client, factory, auth_gateway, google_port = google_api
    google_port.folders = [RemoteFolder("folder-1", "Client A"), RemoteFolder("folder-2", "Client B")]
    login(client, auth_gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    started = client.post("/data-sources/google/oauth/start", json={"organization_id": str(organization_id)}, follow_redirects=False)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    source_id = client.get(f"/data-sources/google/oauth/callback?code=code&state={state}").json()["id"]

    catalog = client.get(f"/data-sources/{source_id}/scope-catalog?organization_id={organization_id}")
    response = client.post(
        f"/workspace-folders/selections?organization_id={organization_id}",
        json={
            "source_id": source_id,
            "mode": "selected",
            "folder_ids": ["folder-2", "folder-1"],
            "include_root_files": True,
            "uniform_access_confirmed": True,
        },
    )
    repeated = client.post(
        f"/workspace-folders/selections?organization_id={organization_id}",
        json={
            "source_id": source_id,
            "mode": "selected",
            "folder_ids": ["folder-1", "folder-2"],
            "include_root_files": True,
            "uniform_access_confirmed": True,
        },
    )

    assert catalog.status_code == 200
    assert catalog.json()["folders"] == [{"id": "folder-1", "name": "Client A"}, {"id": "folder-2", "name": "Client B"}]
    assert catalog.json()["root_files"]["available"] is True
    assert response.status_code == 201
    assert repeated.json()["id"] == response.json()["id"]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(WorkspaceFolder)) == 1
        selections = list(session.scalars(select(WorkspaceFolderSelection).order_by(WorkspaceFolderSelection.kind, WorkspaceFolderSelection.external_folder_id)))
        assert [(item.kind, item.external_folder_id) for item in selections] == [
            ("folder", "folder-1"),
            ("folder", "folder-2"),
            ("root_files", ""),
        ]


def test_scope_api_rejects_empty_selected_scope_or_mixed_all_accessible_scope(google_api) -> None:
    client, factory, auth_gateway, _ = google_api
    login(client, auth_gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    started = client.post("/data-sources/google/oauth/start", json={"organization_id": str(organization_id)}, follow_redirects=False)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    source_id = client.get(f"/data-sources/google/oauth/callback?code=code&state={state}").json()["id"]

    empty = client.post(
        f"/workspace-folders/selections?organization_id={organization_id}",
        json={"source_id": source_id, "mode": "selected", "folder_ids": [], "include_root_files": False, "uniform_access_confirmed": True},
    )
    mixed = client.post(
        f"/workspace-folders/selections?organization_id={organization_id}",
        json={"source_id": source_id, "mode": "all_accessible", "folder_ids": ["folder-1"], "include_root_files": True, "uniform_access_confirmed": True},
    )

    assert empty.status_code == 422
    assert empty.json() == {"detail": "select at least one folder or root files"}
    assert mixed.status_code == 422
    assert mixed.json() == {"detail": "all accessible mode cannot include folder or root selections"}
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(WorkspaceFolder)) == 0


def test_scope_selection_reuses_migrated_legacy_single_folder_workspace(google_api) -> None:
    client, factory, auth_gateway, _ = google_api
    login(client, auth_gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    started = client.post("/data-sources/google/oauth/start", json={"organization_id": str(organization_id)}, follow_redirects=False)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    source_id = UUID(client.get(f"/data-sources/google/oauth/callback?code=code&state={state}").json()["id"])
    with factory.begin() as session:
        legacy = WorkspaceFolder(
            organization_id=organization_id,
            source_id=source_id,
            external_folder_id="folder-1",
            name="Legacy folder",
            uniform_access_confirmed=True,
        )
        session.add(legacy)
        session.flush()
        session.add(WorkspaceFolderSelection(workspace_folder_id=legacy.id, kind="folder", external_folder_id="folder-1"))
        legacy_id = str(legacy.id)

    selected = client.post(
        f"/workspace-folders/selections?organization_id={organization_id}",
        json={"source_id": str(source_id), "mode": "selected", "folder_ids": ["folder-1"], "uniform_access_confirmed": True},
    )

    assert selected.status_code == 201
    assert selected.json()["id"] == legacy_id
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(WorkspaceFolder)) == 1


def test_member_cannot_read_scope_catalog_or_create_scope(google_api) -> None:
    client, factory, auth_gateway, _ = google_api
    login(client, auth_gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    started = client.post("/data-sources/google/oauth/start", json={"organization_id": str(organization_id)}, follow_redirects=False)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    source_id = client.get(f"/data-sources/google/oauth/callback?code=code&state={state}").json()["id"]
    login(client, auth_gateway, code="member", email="member@example.test", subject="member")
    with factory.begin() as session:
        member = session.scalar(select(User).where(User.email == "member@example.test"))
        assert member is not None
        session.add(Membership(organization_id=organization_id, user_id=member.id, role=MembershipRole.MEMBER, is_active=True))

    catalog = client.get(f"/data-sources/{source_id}/scope-catalog?organization_id={organization_id}")
    create = client.post(
        f"/workspace-folders/selections?organization_id={organization_id}",
        json={"source_id": source_id, "mode": "all_accessible", "uniform_access_confirmed": True},
    )

    assert catalog.status_code == 403
    assert create.status_code == 403
