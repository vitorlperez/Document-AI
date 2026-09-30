import importlib
from collections.abc import Generator
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.identity.auth import VerifiedIdentity
from app.identity.models import User
from app.integrations.models import DataSource
from app.library.service import LibraryService
from app.organizations.models import Membership, MembershipRole
from app.workspaces.models import WorkspaceFolder, WorkspaceFolderSelection

GRAPH = "https://graph.microsoft.com/v1.0"
SITE = "contoso.sharepoint.com,g1,g2"
TENANTS = {
    "Bearer contoso-access": "Contoso.SharePoint.com",
    "Bearer fabrikam-access": "fabrikam.sharepoint.com",
}


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
def sharepoint_api(
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
        microsoft_sharepoint_redirect_uri=(
            "http://app.example.test/data-sources/sharepoint/oauth/callback"
        ),
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
    token_calls: list[str] = []

    def post(url: str, *, data: dict[str, str | None], timeout: int) -> httpx.Response:
        assert url == "https://login.microsoftonline.com/organizations/oauth2/v2.0/token"
        assert data["redirect_uri"] == settings.microsoft_sharepoint_redirect_uri
        code = str(data["code"])
        token_calls.append(code)
        tenant = "fabrikam" if code == "fabrikam-code" else "contoso"
        return httpx.Response(
            200,
            json={
                "access_token": f"{tenant}-access",
                "refresh_token": f"{tenant}-refresh-secret",
                "expires_in": 3600,
            },
            request=httpx.Request("POST", url),
        )

    def get(url: str, *, headers: dict[str, str], timeout: int) -> httpx.Response:
        assert headers["Authorization"] in TENANTS
        routes: dict[str, object] = {
            f"{GRAPH}/me?$select=mail,userPrincipalName": {"mail": "admin@contoso.test"},
            f"{GRAPH}/sites/root?$select=siteCollection": {
                "siteCollection": {"hostname": TENANTS[headers["Authorization"]]}
            },
            f"{GRAPH}/sites?search=*&$select=id,displayName,webUrl": {
                "value": [{"id": SITE, "displayName": "Jurídico"}]
            },
            f"{GRAPH}/sites/{SITE}/drives?$select=id,name,driveType": {
                "value": [{"id": "b!d1", "name": "Documentos", "driveType": "documentLibrary"}]
            },
            f"{GRAPH}/drives/b%21d1/root?$select=id": {"id": "01ROOT"},
        }
        if url not in routes:
            raise AssertionError(f"Unexpected Microsoft Graph URL: {url}")
        return httpx.Response(200, json=routes[url], request=httpx.Request("GET", url))

    monkeypatch.setattr("app.integrations.onedrive.httpx.post", post)
    monkeypatch.setattr("app.integrations.onedrive.httpx.get", get)
    with TestClient(app) as client:
        yield client, factory, auth_gateway, token_calls
    Base.metadata.drop_all(engine)
    engine.dispose()


def login(client: TestClient, gateway: FakeAuthGateway, *, code: str, email: str) -> None:
    gateway.identities[code] = VerifiedIdentity(provider="workos", subject=code, email=email)
    started = client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    assert (
        client.get(f"/auth/callback?code={code}&state={state}", follow_redirects=False).status_code
        == 302
    )


def create_organization(client: TestClient) -> UUID:
    response = client.post("/organizations", json={"name": "Acme"})
    assert response.status_code == 201
    return UUID(response.json()["id"])


def start(client: TestClient, organization_id: UUID, source_id: str | None = None):
    suffix = f"&source_id={source_id}" if source_id else ""
    return client.get(
        f"/data-sources/sharepoint/oauth/start?organization_id={organization_id}{suffix}",
        follow_redirects=False,
    )


def connect_sharepoint(client: TestClient, organization_id: UUID) -> str:
    started = start(client, organization_id)
    assert started.status_code == 302
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    response = client.get(f"/data-sources/sharepoint/oauth/callback?code=ms-code&state={state}")
    assert response.status_code == 200
    return response.json()["id"]


def owner_org(sharepoint_api) -> tuple[TestClient, sessionmaker[Session], UUID, str]:
    client, factory, gateway, _ = sharepoint_api
    login(client, gateway, code="owner", email="owner@example.test")
    organization_id = create_organization(client)
    return client, factory, organization_id, connect_sharepoint(client, organization_id)


def test_sharepoint_oauth_hashes_state_encrypts_credentials_and_binds_tenant(
    sharepoint_api,
) -> None:
    client, factory, gateway, token_calls = sharepoint_api
    login(client, gateway, code="owner", email="owner@example.test")
    organization_id = create_organization(client)
    started = start(client, organization_id)
    query = parse_qs(urlparse(started.headers["location"]).query)
    assert urlparse(started.headers["location"]).path == "/organizations/oauth2/v2.0/authorize"
    assert "Sites.Read.All" in query["scope"][0].split()
    assert query["redirect_uri"] == [
        "http://app.example.test/data-sources/sharepoint/oauth/callback"
    ]

    state = query["state"][0]
    completed = client.get(f"/data-sources/sharepoint/oauth/callback?code=ms-code&state={state}")
    replayed = client.get(f"/data-sources/sharepoint/oauth/callback?code=ms-code&state={state}")

    assert completed.status_code == 200
    assert replayed.status_code == 401
    assert token_calls == ["ms-code"]
    with factory() as session:
        source = session.scalar(select(DataSource))
        assert source is not None
        assert source.provider == "sharepoint"
        assert source.provider_account_id == "contoso.sharepoint.com"
        assert source.encrypted_credentials is not None
        assert "contoso-refresh-secret" not in source.encrypted_credentials
        assert "contoso-access" not in source.encrypted_credentials


def test_sharepoint_reconnect_to_other_tenant_is_rejected_with_html_redirect(
    sharepoint_api,
) -> None:
    client, factory, organization_id, source_id = owner_org(sharepoint_api)
    started = start(client, organization_id, source_id)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    callback = client.get(
        f"/data-sources/sharepoint/oauth/callback?code=fabrikam-code&state={state}",
        headers={"accept": "text/html"},
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert callback.headers["location"].endswith(
        f"/companies/{organization_id}/integrations?error=sharepoint_tenant_mismatch"
    )
    with factory() as session:
        source = session.get(DataSource, UUID(source_id))
        assert source is not None
        assert source.provider_account_id == "contoso.sharepoint.com"


def test_sharepoint_start_without_config_redirects_html_to_unavailable_notice(
    sharepoint_api,
) -> None:
    client, _factory, organization_id, _source_id = owner_org(sharepoint_api)
    client.app.state.settings.microsoft_sharepoint_redirect_uri = None
    url = f"/data-sources/sharepoint/oauth/start?organization_id={organization_id}"
    browser = client.get(url, headers={"accept": "text/html"}, follow_redirects=False)
    assert browser.status_code == 303
    assert browser.headers["location"].endswith(
        f"/companies/{organization_id}/integrations?error=sharepoint_unavailable"
    )
    assert client.get(url, follow_redirects=False).status_code == 503


def test_member_cannot_start_sharepoint_oauth(sharepoint_api) -> None:
    client, factory, organization_id, source_id = owner_org(sharepoint_api)
    _, _, gateway, _ = sharepoint_api
    login(client, gateway, code="member", email="member@example.test")
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
    assert start(client, organization_id).status_code == 403
    catalog = client.get(
        f"/data-sources/{source_id}/scope-catalog?organization_id={organization_id}"
    )
    assert catalog.status_code == 403


def test_sharepoint_source_of_org_a_is_invisible_to_org_b_owner(sharepoint_api) -> None:
    client, _, organization_a, source_a = owner_org(sharepoint_api)
    _, _, gateway, token_calls = sharepoint_api
    login(client, gateway, code="owner-b", email="owner-b@example.test")
    organization_b = create_organization(client)
    assert start(client, organization_a).status_code == 403
    assert start(client, organization_b, source_a).status_code == 403
    catalog = client.get(f"/data-sources/{source_a}/scope-catalog?organization_id={organization_b}")
    assert catalog.status_code == 403
    assert "Jurídico" not in catalog.text
    assert token_calls == ["ms-code"]


def test_second_source_for_same_tenant_in_same_org_violates_unique_index(sharepoint_api) -> None:
    _, factory, organization_id, source_id = owner_org(sharepoint_api)
    with factory() as session:
        existing = session.get(DataSource, UUID(source_id))
        assert existing is not None
        # Same binding under another provider is unaffected by the partial index.
        session.add(
            DataSource(
                organization_id=organization_id,
                provider="onedrive",
                status="connected",
                provider_account_id=existing.provider_account_id,
                connected_by_user_id=existing.connected_by_user_id,
            )
        )
        session.flush()
        session.add(
            DataSource(
                organization_id=organization_id,
                provider="sharepoint",
                status="connected",
                provider_account_id=existing.provider_account_id,
                connected_by_user_id=existing.connected_by_user_id,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()


def test_sharepoint_scope_catalog_lists_sites_libraries_and_disables_all_accessible(
    sharepoint_api,
) -> None:
    client, _, organization_id, source_id = owner_org(sharepoint_api)
    catalog = client.get(
        f"/data-sources/{source_id}/scope-catalog?organization_id={organization_id}"
    )
    assert catalog.status_code == 200
    body = catalog.json()
    assert body["folders"] == [
        {"id": f"site|{SITE}", "name": "Jurídico", "selectable": False, "parent_ids": []},
        {
            "id": "b!d1|01ROOT",
            "name": "Documentos",
            "selectable": True,
            "parent_ids": [f"site|{SITE}"],
        },
    ]
    assert body["root_files"]["available"] is False
    assert body["all_accessible"]["available"] is False


@pytest.mark.parametrize(
    "payload",
    [
        {"mode": "all_accessible"},
        {"mode": "selected", "folder_ids": ["b!d1|01ROOT"], "include_root_files": True},
        {"mode": "selected", "folder_ids": [f"site|{SITE}"]},
    ],
)
def test_sharepoint_selection_rejects_all_accessible_root_files_and_sites_with_422(
    sharepoint_api, payload
) -> None:
    client, _, organization_id, source_id = owner_org(sharepoint_api)
    selected = client.post(
        f"/workspace-folders/selections?organization_id={organization_id}",
        json={"source_id": source_id, "uniform_access_confirmed": True, **payload},
    )
    assert selected.status_code == 422


def test_sharepoint_selection_accepts_library_and_persists_selection_kind_folder(
    sharepoint_api,
) -> None:
    client, factory, organization_id, source_id = owner_org(sharepoint_api)
    selected = client.post(
        f"/workspace-folders/selections?organization_id={organization_id}",
        json={
            "source_id": source_id,
            "mode": "selected",
            "folder_ids": ["b!d1|01ROOT"],
            "uniform_access_confirmed": True,
        },
    )
    assert selected.status_code == 201
    with factory() as session:
        workspace = session.get(WorkspaceFolder, UUID(selected.json()["id"]))
        assert workspace is not None and workspace.source_id == UUID(source_id)
        rows = list(
            session.scalars(
                select(WorkspaceFolderSelection).where(
                    WorkspaceFolderSelection.workspace_folder_id == workspace.id
                )
            )
        )
        assert [(row.kind, row.external_folder_id) for row in rows] == [("folder", "b!d1|01ROOT")]


def test_library_root_label_for_sharepoint(sharepoint_api) -> None:
    _, factory, organization_id, source_id = owner_org(sharepoint_api)
    with factory() as session:
        source = session.get(DataSource, UUID(source_id))
        assert source is not None
        root = LibraryService(session)._root(
            organization_id=OrganizationScope(organization_id).organization_id, source=source
        )
        assert root.name == "SharePoint"
