import importlib
from collections.abc import Generator
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.models import Base
from app.identity.auth import VerifiedIdentity
from app.identity.models import User
from app.ingestion.models import ProcessingJob, ProcessingJobStatus
from app.ingestion.service import DiscoveredDocument
from app.integrations.models import DataSource
from app.knowledge.models import Document
from app.library.service import LibraryService
from app.organizations.models import Organization
from app.workspaces.models import WorkspaceFolder


class FakeAuthGateway:
    def authorization_url(self, *, state: str) -> str:
        return f"https://auth.example.test/login?state={state}"

    def exchange_code(self, *, code: str) -> VerifiedIdentity:
        return VerifiedIdentity(provider="workos", subject=code, email=f"{code}@example.test")


@pytest.fixture()
def api(monkeypatch: pytest.MonkeyPatch) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")
    main = importlib.import_module("app.main")
    app = main.create_app(Settings(database_url="postgresql+psycopg://test:test@localhost/test", public_app_url="http://app.example.test"))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app.state.session_factory = factory
    app.state.auth_gateway = FakeAuthGateway()
    with TestClient(app) as client:
        yield client, factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def login(client: TestClient, code: str = "member") -> None:
    started = client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    assert client.get(f"/auth/callback?code={code}&state={state}", follow_redirects=False).status_code == 302


def seed_library(factory: sessionmaker[Session], organization_id: str) -> str:
    with factory() as session:
        organization = session.get(Organization, UUID(organization_id))
        user = session.query(User).filter_by(email="member@example.test").one()
        assert organization is not None
        source = DataSource(organization_id=organization.id, provider="google_drive", encrypted_credentials="encrypted", status="connected", connected_by_user_id=user.id)
        session.add(source)
        session.flush()
        workspace = WorkspaceFolder(organization_id=organization.id, source_id=source.id, external_folder_id="scope", name="Scope", uniform_access_confirmed=True, status="ready")
        session.add(workspace)
        session.flush()
        session.add(Document(organization_id=organization.id, workspace_folder_id=workspace.id, external_file_id="brief", name="Brief.pdf", mime_type="application/pdf", source_url="https://drive.example.test/brief", content_hash="hash", processing_version="v1", index_status="indexed"))
        session.flush()
        LibraryService(session).project_successful_sync(organization_id=organization.id, source=source, documents=[DiscoveredDocument("brief", "Brief.pdf", "application/pdf", "https://drive.example.test/brief", text="text")], folders=[])
        session.commit()
        return str(source.id)


def test_company_library_is_member_scoped_and_nodes_use_uuids(api: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    source_id = seed_library(factory, organization)

    roots = client.get(f"/library?organization_id={organization}")
    assert roots.status_code == 200
    root = roots.json()["items"][0]
    assert root["id"] != source_id and root["kind"] == "source"
    children = client.get(f"/library/nodes/{root['id']}/children?organization_id={organization}")
    assert children.status_code == 200
    assert children.json()["items"] == [
        {"id": children.json()["items"][0]["id"], "parent_id": root["id"], "source_id": source_id, "kind": "file", "name": "Brief.pdf", "mime_type": "application/pdf", "source_url": "https://drive.example.test/brief", "workspace_folder_ids": children.json()["items"][0]["workspace_folder_ids"]}
    ]
    assert len(children.json()["items"][0]["workspace_folder_ids"]) == 1


def test_company_library_does_not_disclose_foreign_node(api: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    seed_library(factory, organization)
    root = client.get(f"/library?organization_id={organization}").json()["items"][0]

    login(client, "outsider")
    outsider_org = client.post("/organizations", json={"name": "Other"}).json()["id"]
    response = client.get(f"/library/nodes/{root['id']}/children?organization_id={outsider_org}")
    assert response.status_code == 404
    assert "Google Drive" not in response.text and "Brief.pdf" not in response.text


def test_member_can_search_library_names_and_see_own_sync_phases(api: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    seed_library(factory, organization)
    with factory() as session:
        workspace = session.query(WorkspaceFolder).filter_by(organization_id=UUID(organization)).one()
        session.add(ProcessingJob(organization_id=workspace.organization_id, workspace_folder_id=workspace.id, idempotency_key="library-sync", status=ProcessingJobStatus.SYNCING))
        session.commit()

    search = client.get(f"/library/search?organization_id={organization}&query=brief")
    contexts = client.get(f"/library/question-contexts?organization_id={organization}")
    syncs = client.get(f"/library/syncs?organization_id={organization}")
    assert search.status_code == contexts.status_code == syncs.status_code == 200
    assert [item["name"] for item in search.json()["items"]] == ["Brief.pdf"]
    assert [item["name"] for item in contexts.json()["items"]] == ["Scope"]
    assert [item["status"] for item in syncs.json()["items"]] == ["syncing"]

    login(client, "outsider")
    outsider_org = client.post("/organizations", json={"name": "Other"}).json()["id"]
    forbidden = client.get(f"/library/search?organization_id={organization}&query=brief")
    own_empty = client.get(f"/library/syncs?organization_id={outsider_org}")
    assert forbidden.status_code == 403 and "Brief.pdf" not in forbidden.text
    assert own_empty.status_code == 200 and own_empty.json()["items"] == []
