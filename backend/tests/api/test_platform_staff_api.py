import importlib
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.models import Base
from app.identity.models import User, UserSession
from app.integrations.models import DataSource
from app.knowledge.models import Document
from app.organizations.models import Organization, PlatformStaff, StaffAccessGrant
from app.workspaces.models import WorkspaceFolder


@pytest.fixture()
def platform_api(monkeypatch: pytest.MonkeyPatch) -> Generator[tuple[TestClient, sessionmaker[Session]]]:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db")
    main = importlib.import_module("app.main")
    app = main.create_app(
        Settings(
            database_url="postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db",
            public_app_url="http://app.example.test",
            environment="development",
        )
    )
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app.state.session_factory = factory
    with TestClient(app) as client:
        yield client, factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def authenticate(client: TestClient, factory: sessionmaker[Session], *, staff: bool) -> tuple[User, Organization]:
    with factory.begin() as session:
        user = User(email="staff@example.test" if staff else "member@example.test")
        organization = Organization(name="Acme")
        session.add_all([user, organization])
        session.flush()
        raw_secret = "a-secret-that-is-not-returned"
        session.add(
            UserSession(
                user_id=user.id,
                secret_hash=sha256(raw_secret.encode()).hexdigest(),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        if staff:
            platform_staff = PlatformStaff(user_id=user.id)
            session.add(platform_staff)
    client.cookies.set("document_intelligence_session", raw_secret)
    return user, organization


def add_private_document(factory: sessionmaker[Session], *, user: User, organization: Organization) -> WorkspaceFolder:
    """Seed private content solely to prove the support overview cannot leak it."""
    with factory.begin() as session:
        source = DataSource(
            organization_id=organization.id,
            provider="google_drive",
            encrypted_credentials="encrypted",
            connected_by_user_id=user.id,
        )
        session.add(source)
        session.flush()
        folder = WorkspaceFolder(
            organization_id=organization.id,
            source_id=source.id,
            external_folder_id="private-folder",
            name="Private client folder",
            uniform_access_confirmed=True,
            status="partial_failure",
        )
        session.add(folder)
        session.flush()
        session.add(
            Document(
                organization_id=organization.id,
                workspace_folder_id=folder.id,
                external_file_id="secret-contract",
                name="Secret contract.pdf",
                mime_type="application/pdf",
                source_url="https://drive.example.test/secret-contract",
                content_hash="a" * 64,
                index_status="failed",
                error_code="EXTRACTION_FAILED",
            )
        )
    return folder


def test_platform_staff_lists_all_companies_and_metadata(platform_api) -> None:
    client, factory = platform_api
    _, organization = authenticate(client, factory, staff=True)
    with factory.begin() as session:
        second_organization = Organization(name="Beta")
        session.add(second_organization)
        session.flush()

    companies = client.get("/platform/companies")
    overview = client.get(f"/platform/companies/{second_organization.id}/overview")
    me = client.get("/me")

    assert companies.status_code == overview.status_code == me.status_code == 200
    assert companies.json() == [
        {"organization_id": str(organization.id), "name": "Acme"},
        {"organization_id": str(second_organization.id), "name": "Beta"},
    ]
    assert overview.json()["organization_id"] == str(second_organization.id)
    assert overview.json()["folders"] == []
    assert me.json()["is_platform_staff"] is True
    assert client.get("/organizations").json() == []
    assert client.get(f"/workspace-folders?organization_id={organization.id}").status_code == 403
    assert client.get(f"/organizations/{organization.id}/members").status_code == 403


def test_regular_user_and_forged_company_uuid_cannot_use_platform_support(platform_api) -> None:
    client, factory = platform_api
    _, organization = authenticate(client, factory, staff=False)

    assert client.get("/platform/companies").status_code == 403
    assert client.get(f"/platform/companies/{organization.id}/overview").status_code == 403


def test_platform_staff_cannot_use_tenant_content_or_drive_apis_and_overview_redacts_document_data(platform_api) -> None:
    client, factory = platform_api
    user, organization = authenticate(client, factory, staff=True)
    folder = add_private_document(factory, user=user, organization=organization)

    overview = client.get(f"/platform/companies/{organization.id}/overview")
    body = overview.json()
    serialized = overview.text

    assert overview.status_code == 200
    assert body["folders"] == [
        {
            "id": str(folder.id),
            "name": "Private client folder",
            "status": "partial_failure",
            "last_synced_at": None,
            "failure_summary": [{"error_code": "EXTRACTION_FAILED", "count": 1}],
        }
    ]
    assert "Secret contract.pdf" not in serialized
    assert "drive.example.test" not in serialized
    assert "secret-contract" not in serialized

    denied = [
        client.get(f"/workspace-folders?organization_id={organization.id}"),
        client.get(f"/workspace-folders/{folder.id}/documents?organization_id={organization.id}"),
        client.get(f"/workspace-folders/{folder.id}/documents/failures?organization_id={organization.id}"),
        client.post(f"/workspace-folders/{folder.id}/search?organization_id={organization.id}", json={"query": "contract"}),
        client.post(f"/workspace-folders/{folder.id}/questions?organization_id={organization.id}", json={"question": "What does it say?"}),
        client.get(f"/workspace-folders/{folder.id}/saved-queries?organization_id={organization.id}"),
        client.post(f"/workspace-folders/{folder.id}/saved-queries?organization_id={organization.id}", json={"name": "Secret", "query": "contract", "filters": {}}),
        client.get(f"/data-sources?organization_id={organization.id}"),
        client.post("/data-sources/google/oauth/start", json={"organization_id": str(organization.id)}),
        client.get(f"/organizations/{organization.id}/members"),
    ]

    assert [response.status_code for response in denied] == [403] * len(denied)


def test_expired_staff_grant_does_not_remove_global_support_access(platform_api) -> None:
    client, factory = platform_api
    user, organization = authenticate(client, factory, staff=True)
    with factory.begin() as session:
        staff = session.query(PlatformStaff).filter_by(user_id=user.id).one()
        session.add(
            StaffAccessGrant(
                platform_staff_id=staff.id,
                organization_id=organization.id,
                granted_by_user_id=user.id,
                reason="Legacy grant",
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )

    assert client.get("/platform/companies").json() == [{"organization_id": str(organization.id), "name": "Acme"}]
    assert client.get(f"/platform/companies/{organization.id}/overview").status_code == 200
