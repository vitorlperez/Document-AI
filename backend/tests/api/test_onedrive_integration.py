import importlib
from collections.abc import Generator
from hashlib import sha256
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.models import Base
from app.identity.auth import VerifiedIdentity
from app.identity.models import User
from app.integrations.models import DataSource, OAuthConnectionState
from app.organizations.models import Membership, MembershipRole
from app.workspaces.models import WorkspaceFolder, WorkspaceFolderSelection


class FakeAuthGateway:
    def __init__(self) -> None:
        self.identities: dict[str, VerifiedIdentity] = {}

    def authorization_url(
        self, *, state: str, screen_hint: str | None = None, max_age: int | None = None
    ) -> str:
        del screen_hint, max_age
        return f"https://auth.example.test/login?state={state}"

    def exchange_code(self, *, code: str) -> VerifiedIdentity:
        return self.identities[code]

    def logout_url(self, *, session_id: str, return_to: str) -> str:
        return f"https://auth.example.test/logout?sid={session_id}&return_to={return_to}"


@pytest.fixture()
def onedrive_api(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[TestClient, sessionmaker[Session], FakeAuthGateway, list[str]], None, None]:
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db"
    )
    main = importlib.import_module("app.main")
    settings = Settings(
        database_url="postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db",
        public_app_url="http://app.example.test",
        environment="development",
        microsoft_oauth_client_id="microsoft-client",
        microsoft_oauth_client_secret="microsoft-secret",
        microsoft_oauth_redirect_uri="http://app.example.test/data-sources/onedrive/oauth/callback",
        microsoft_token_encryption_key=Fernet.generate_key().decode(),
    )
    app = main.create_app(settings)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    auth_gateway = FakeAuthGateway()
    app.state.session_factory = factory
    app.state.auth_gateway = auth_gateway
    graph_calls: list[str] = []
    token_calls: list[str] = []

    def post(url: str, *, data: dict[str, str | None], timeout: int) -> httpx.Response:
        assert timeout == 15
        assert url == "https://login.microsoftonline.com/common/oauth2/v2.0/token"
        assert data["client_id"] == "microsoft-client"
        assert data["client_secret"] == "microsoft-secret"
        assert data["grant_type"] == "authorization_code"
        code = str(data["code"])
        token_calls.append(code)
        personal_account = code == "personal-code"
        return httpx.Response(
            200,
            json={
                "access_token": (
                    "personal-access-secret" if personal_account else "onedrive-access-secret"
                ),
                "refresh_token": (
                    "personal-refresh-secret" if personal_account else "onedrive-refresh-secret"
                ),
                "expires_in": 3600,
            },
            request=httpx.Request("POST", url),
        )

    def get(url: str, *, headers: dict[str, str], timeout: int) -> httpx.Response:
        graph_calls.append(url)
        personal_account = headers["Authorization"] == "Bearer personal-access-secret"
        assert headers["Authorization"] in {
            "Bearer onedrive-access-secret",
            "Bearer personal-access-secret",
        }
        assert timeout == 20
        if url == "https://graph.microsoft.com/v1.0/me?$select=mail,userPrincipalName":
            payload: dict[str, object] = (
                {"mail": None, "userPrincipalName": "Personal.Owner@outlook.com"}
                if personal_account
                else {"mail": "drive.owner@example.test"}
            )
        elif url == "https://graph.microsoft.com/v1.0/me/drive?$select=id":
            payload = {"id": "personal-drive-id" if personal_account else "drive-1"}
        elif url == "https://graph.microsoft.com/v1.0/me/drive/root?$select=id":
            payload = {"id": "personal-root-item" if personal_account else "root-item"}
        elif (
            url
            == "https://graph.microsoft.com/v1.0/me/drive/items/root-item/children?$select=id,name,folder,parentReference"
        ):
            payload = {
                "value": [
                    {
                        "id": "folder-1",
                        "name": "Client Files",
                        "folder": {"childCount": 1},
                        "parentReference": {"driveId": "drive-1", "id": "root"},
                    },
                    {
                        "id": "root-file",
                        "name": "Readme.txt",
                        "file": {"mimeType": "text/plain"},
                        "parentReference": {"driveId": "drive-1", "id": "root"},
                    },
                ]
            }
        elif (
            url
            == "https://graph.microsoft.com/v1.0/me/drive/items/personal-root-item/children?$select=id,name,folder,parentReference"
        ):
            payload = {
                "value": [
                    {
                        "id": "personal-folder-id",
                        "name": "Personal Documents",
                        "folder": {"childCount": 1},
                        "parentReference": {"driveId": "personal-drive-id", "id": "root"},
                    }
                ]
            }
        elif (
            url
            == "https://graph.microsoft.com/v1.0/me/drive/items/folder-1/children?$select=id,name,folder,parentReference"
        ) or (
            url
            == "https://graph.microsoft.com/v1.0/me/drive/items/personal-folder-id/children?$select=id,name,folder,parentReference"
        ):
            payload = {"value": []}
        else:
            raise AssertionError(f"Unexpected Microsoft Graph URL: {url}")
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr("app.integrations.onedrive.httpx.post", post)
    monkeypatch.setattr("app.integrations.onedrive.httpx.get", get)
    with TestClient(app) as client:
        yield client, factory, auth_gateway, token_calls
    Base.metadata.drop_all(engine)
    engine.dispose()


def login(
    client: TestClient,
    gateway: FakeAuthGateway,
    *,
    code: str,
    email: str,
    subject: str,
) -> None:
    gateway.identities[code] = VerifiedIdentity(provider="workos", subject=subject, email=email)
    started = client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    response = client.get(f"/auth/callback?code={code}&state={state}", follow_redirects=False)
    assert response.status_code == 302


def create_organization(client: TestClient) -> UUID:
    response = client.post("/organizations", json={"name": "Acme"})
    assert response.status_code == 201
    return UUID(response.json()["id"])


def connect_onedrive(
    client: TestClient,
    factory: sessionmaker[Session],
    organization_id: UUID,
    *,
    code: str = "ms-code",
) -> str:
    started = client.get(
        f"/data-sources/onedrive/oauth/start?organization_id={organization_id}",
        follow_redirects=False,
    )
    assert started.status_code == 302
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    response = client.get(f"/data-sources/onedrive/oauth/callback?code={code}&state={state}")
    assert response.status_code == 200
    source_id = response.json()["id"]
    return source_id


def test_onedrive_oauth_hashes_state_and_encrypts_credentials_and_is_one_time(onedrive_api) -> None:
    client, factory, auth_gateway, token_calls = onedrive_api
    login(client, auth_gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)

    started = client.get(
        f"/data-sources/onedrive/oauth/start?organization_id={organization_id}",
        follow_redirects=False,
    )
    assert started.status_code == 302
    auth_url = urlparse(started.headers["location"])
    query = parse_qs(auth_url.query)
    state = query["state"][0]
    assert auth_url.netloc == "login.microsoftonline.com"
    assert auth_url.path == "/common/oauth2/v2.0/authorize"
    assert query["client_id"] == ["microsoft-client"]
    assert query["prompt"] == ["select_account"]
    assert query["scope"] == ["openid profile offline_access User.Read Files.Read"]
    assert query["response_type"] == ["code"]

    with factory() as session:
        oauth_state = session.scalar(select(OAuthConnectionState))
        assert oauth_state is not None
        assert oauth_state.organization_id == organization_id
        assert oauth_state.state_hash == sha256(state.encode()).hexdigest()
        session_secret = client.cookies.get("document_intelligence_session")
        assert session_secret is not None
        assert oauth_state.session_hash == sha256(session_secret.encode()).hexdigest()
        assert state not in oauth_state.state_hash

    completed = client.get(f"/data-sources/onedrive/oauth/callback?code=ms-code&state={state}")
    replayed = client.get(f"/data-sources/onedrive/oauth/callback?code=ms-code&state={state}")

    assert completed.status_code == 200
    assert completed.json()["status"] == "connected"
    assert replayed.status_code == 401
    assert token_calls == ["ms-code"]
    with factory() as session:
        source = session.scalar(select(DataSource))
        assert source is not None
        assert source.provider == "onedrive"
        assert source.organization_id == organization_id
        assert source.account_email == "drive.owner@example.test"
        assert source.encrypted_credentials is not None
        assert "onedrive-access-secret" not in source.encrypted_credentials
        assert "onedrive-refresh-secret" not in source.encrypted_credentials


def test_onedrive_callback_rejects_missing_or_mismatched_state_without_exchange(
    onedrive_api,
) -> None:
    client, factory, auth_gateway, token_calls = onedrive_api
    login(client, auth_gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    client.get(f"/data-sources/onedrive/oauth/start?organization_id={organization_id}")

    missing = client.get("/data-sources/onedrive/oauth/callback?code=ms-code&state=missing-state")
    rejected_error = client.get(
        "/data-sources/onedrive/oauth/callback?code=ms-code&state=missing-state&error=access_denied"
    )

    assert missing.status_code == 401
    assert rejected_error.status_code == 401
    assert token_calls == []
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(DataSource)) == 0


def test_onedrive_callback_rejects_state_bound_to_another_browser_session(onedrive_api) -> None:
    client, _, auth_gateway, token_calls = onedrive_api
    login(client, auth_gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    started = client.get(
        f"/data-sources/onedrive/oauth/start?organization_id={organization_id}",
        follow_redirects=False,
    )
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]

    login(
        client, auth_gateway, code="another-user", email="another@example.test", subject="another"
    )
    response = client.get(f"/data-sources/onedrive/oauth/callback?code=ms-code&state={state}")

    assert response.status_code == 401
    assert token_calls == []


def test_onedrive_scope_catalog_lists_remote_folders_and_selection_is_persisted(
    onedrive_api,
) -> None:
    client, factory, auth_gateway, _ = onedrive_api
    login(client, auth_gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    source_id = connect_onedrive(client, factory, organization_id)

    catalog = client.get(
        f"/data-sources/{source_id}/scope-catalog?organization_id={organization_id}"
    )
    selected = client.post(
        f"/workspace-folders/selections?organization_id={organization_id}",
        json={
            "source_id": source_id,
            "mode": "selected",
            "folder_ids": ["folder-1"],
            "include_root_files": True,
            "uniform_access_confirmed": True,
        },
    )

    assert catalog.status_code == 200
    assert catalog.json() == {
        "folders": [{"id": "folder-1", "name": "Client Files"}],
        "root_files": {"available": True, "label": "Arquivos avulsos da raiz"},
        "all_accessible": {"available": True, "label": "Todo o OneDrive acessível"},
    }
    assert selected.status_code == 201
    with factory() as session:
        workspace = session.get(WorkspaceFolder, UUID(selected.json()["id"]))
        assert workspace is not None
        assert workspace.source_id == UUID(source_id)
        rows = list(
            session.scalars(
                select(WorkspaceFolderSelection)
                .where(WorkspaceFolderSelection.workspace_folder_id == workspace.id)
                .order_by(WorkspaceFolderSelection.kind)
            )
        )
        assert [(item.kind, item.external_folder_id) for item in rows] == [
            ("folder", "folder-1"),
            ("root_files", ""),
        ]


def test_personal_microsoft_account_connects_and_lists_its_graph_catalog(onedrive_api) -> None:
    client, factory, auth_gateway, token_calls = onedrive_api
    login(client, auth_gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)

    source_id = connect_onedrive(client, factory, organization_id, code="personal-code")
    catalog = client.get(
        f"/data-sources/{source_id}/scope-catalog?organization_id={organization_id}"
    )

    assert token_calls == ["personal-code"]
    assert catalog.status_code == 200
    assert catalog.json() == {
        "folders": [{"id": "personal-folder-id", "name": "Personal Documents"}],
        "root_files": {"available": True, "label": "Arquivos avulsos da raiz"},
        "all_accessible": {"available": True, "label": "Todo o OneDrive acessível"},
    }
    with factory() as session:
        source = session.get(DataSource, UUID(source_id))
        assert source is not None
        assert source.account_email == "personal.owner@outlook.com"
        assert source.provider_account_id == "personal-drive-id"
        assert source.status == "connected"


def test_onedrive_reauthorization_clears_old_account_delta_cursors(onedrive_api) -> None:
    client, factory, auth_gateway, _ = onedrive_api
    login(client, auth_gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    source_id = connect_onedrive(client, factory, organization_id)
    selected = client.post(
        f"/workspace-folders/selections?organization_id={organization_id}",
        json={
            "source_id": source_id,
            "mode": "all_accessible",
            "uniform_access_confirmed": True,
        },
    )
    with factory.begin() as session:
        selection = session.scalar(
            select(WorkspaceFolderSelection).where(
                WorkspaceFolderSelection.workspace_folder_id == UUID(selected.json()["id"])
            )
        )
        assert selection is not None
        selection.encrypted_delta_link = "previous-account-cursor"

    started = client.get(
        f"/data-sources/onedrive/oauth/start?organization_id={organization_id}&source_id={source_id}",
        follow_redirects=False,
    )
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    callback = client.get(
        f"/data-sources/onedrive/oauth/callback?code=ms-code&state={state}",
        follow_redirects=False,
    )

    assert started.status_code == 302
    assert callback.status_code == 200
    with factory() as session:
        selection = session.scalar(
            select(WorkspaceFolderSelection).where(
                WorkspaceFolderSelection.workspace_folder_id == UUID(selected.json()["id"])
            )
        )
        assert selection is not None
        assert selection.encrypted_delta_link is None


def test_onedrive_reauthorization_rejects_a_different_drive_account(
    monkeypatch: pytest.MonkeyPatch, onedrive_api
) -> None:
    client, factory, auth_gateway, _ = onedrive_api
    login(client, auth_gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    source_id = connect_onedrive(client, factory, organization_id)
    with factory() as session:
        source = session.get(DataSource, UUID(source_id))
        assert source is not None
        original_credentials = source.encrypted_credentials
        assert source.provider_account_id == "drive-1"

    started = client.get(
        f"/data-sources/onedrive/oauth/start?organization_id={organization_id}&source_id={source_id}",
        follow_redirects=False,
    )
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    monkeypatch.setattr(
        "app.integrations.onedrive.MicrosoftGraphClient.drive_id",
        lambda _client, *, credentials: "another-drive",
    )
    callback = client.get(
        f"/data-sources/onedrive/oauth/callback?code=ms-code&state={state}",
        follow_redirects=False,
    )

    assert callback.status_code == 409
    with factory() as session:
        source = session.get(DataSource, UUID(source_id))
        assert source is not None
        assert source.provider_account_id == "drive-1"
        assert source.encrypted_credentials == original_credentials


def test_member_cannot_start_onedrive_or_read_or_create_its_scopes(onedrive_api) -> None:
    client, factory, auth_gateway, token_calls = onedrive_api
    login(client, auth_gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    source_id = connect_onedrive(client, factory, organization_id)
    login(client, auth_gateway, code="member", email="member@example.test", subject="member")
    with factory.begin() as session:
        member = session.scalar(select(User).where(User.email == "member@example.test"))
        assert member is not None
        session.add(
            Membership(
                organization_id=organization_id,
                user_id=member.id,
                role=MembershipRole.MEMBER,
                is_active=True,
            )
        )

    start = client.get(
        f"/data-sources/onedrive/oauth/start?organization_id={organization_id}",
        follow_redirects=False,
    )
    catalog = client.get(
        f"/data-sources/{source_id}/scope-catalog?organization_id={organization_id}"
    )
    create_scope = client.post(
        f"/workspace-folders/selections?organization_id={organization_id}",
        json={
            "source_id": source_id,
            "mode": "all_accessible",
            "uniform_access_confirmed": True,
        },
    )
    disconnect = client.delete(f"/data-sources/{source_id}?organization_id={organization_id}")

    assert start.status_code == 403
    assert catalog.status_code == 403
    assert create_scope.status_code == 403
    assert disconnect.status_code == 403
    assert token_calls == ["ms-code"]
    with factory() as session:
        source = session.get(DataSource, UUID(source_id))
        assert source is not None
        assert source.status == "connected"
        assert source.encrypted_credentials is not None


def test_onedrive_owner_cannot_start_or_read_a_source_across_organizations(onedrive_api) -> None:
    client, factory, auth_gateway, token_calls = onedrive_api
    login(client, auth_gateway, code="owner-a", email="owner-a@example.test", subject="owner-a")
    organization_a = create_organization(client)
    source_a = connect_onedrive(client, factory, organization_a)

    login(client, auth_gateway, code="owner-b", email="owner-b@example.test", subject="owner-b")
    organization_b = create_organization(client)

    start_organization_a = client.get(
        f"/data-sources/onedrive/oauth/start?organization_id={organization_a}",
        follow_redirects=False,
    )
    reauthorize_foreign_source = client.get(
        f"/data-sources/onedrive/oauth/start?organization_id={organization_b}&source_id={source_a}",
        follow_redirects=False,
    )
    catalog_foreign_source = client.get(
        f"/data-sources/{source_a}/scope-catalog?organization_id={organization_b}"
    )
    folders_foreign_source = client.get(
        f"/data-sources/{source_a}/folders?organization_id={organization_b}"
    )

    assert start_organization_a.status_code == 403
    assert reauthorize_foreign_source.status_code == 403
    assert catalog_foreign_source.status_code == 403
    assert folders_foreign_source.status_code == 403
    assert "drive.owner@example.test" not in catalog_foreign_source.text
    assert token_calls == ["ms-code"]
    with factory() as session:
        source = session.get(DataSource, UUID(source_a))
        assert source is not None
        assert source.organization_id == organization_a
        assert source.status == "connected"
        states = list(session.scalars(select(OAuthConnectionState)))
        assert len(states) == 1


def test_member_cannot_select_notion_scope(onedrive_api) -> None:
    client, factory, auth_gateway, _ = onedrive_api
    login(client, auth_gateway, code="owner", email="owner@example.test", subject="owner")
    organization_id = create_organization(client)
    with factory.begin() as session:
        owner = session.scalar(select(User).where(User.email == "owner@example.test"))
        assert owner is not None
        source = DataSource(
            organization_id=organization_id,
            provider="notion",
            encrypted_credentials="encrypted-notion-token",
            status="connected",
            connected_by_user_id=owner.id,
        )
        session.add(source)
        session.flush()
        source_id = source.id

    login(client, auth_gateway, code="member", email="member@example.test", subject="member")
    with factory.begin() as session:
        member = session.scalar(select(User).where(User.email == "member@example.test"))
        assert member is not None
        session.add(
            Membership(
                organization_id=organization_id,
                user_id=member.id,
                role=MembershipRole.MEMBER,
                is_active=True,
            )
        )

    response = client.post(
        f"/workspace-folders/selections?organization_id={organization_id}",
        json={
            "source_id": str(source_id),
            "mode": "all_accessible",
            "uniform_access_confirmed": True,
        },
    )

    assert response.status_code == 403
