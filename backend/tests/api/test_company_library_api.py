import importlib
from collections.abc import Generator
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.identity.auth import VerifiedIdentity
from app.identity.models import User
from app.ingestion.models import ProcessingJob, ProcessingJobStatus
from app.ingestion.service import DiscoveredDocument
from app.integrations.google_drive import RemoteFolder
from app.integrations.models import DataSource
from app.knowledge.models import Document
from app.library.models import LibraryNode
from app.library.service import LibraryService
from app.organizations.models import Organization
from app.workspaces.models import WorkspaceFolder


class FakeAuthGateway:
    def authorization_url(self, *, state: str, screen_hint: str | None = None, max_age: int | None = None) -> str:
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
        {
            "id": children.json()["items"][0]["id"],
            "parent_id": root["id"],
            "source_id": source_id,
            "kind": "file",
            "external_id": children.json()["items"][0]["external_id"],
            "name": "Brief.pdf",
            "mime_type": "application/pdf",
            "source_url": "https://drive.example.test/brief",
            "workspace_folder_ids": children.json()["items"][0]["workspace_folder_ids"],
            "workspace_documents": children.json()["items"][0]["workspace_documents"],
        }
    ]
    assert len(children.json()["items"][0]["workspace_folder_ids"]) == 1
    assert len(children.json()["items"][0]["workspace_documents"]) == 1
    assert UUID(children.json()["items"][0]["workspace_documents"][0]["document_id"])


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


def test_library_children_loads_document_provenance_in_one_query(
    api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    source_id = seed_library(factory, organization)
    root = client.get(f"/library?organization_id={organization}").json()["items"][0]
    with factory() as session:
        workspace = session.query(WorkspaceFolder).filter_by(organization_id=UUID(organization)).one()
        for index in range(12):
            external_id = f"extra-{index}"
            session.add(Document(
                organization_id=workspace.organization_id, workspace_folder_id=workspace.id,
                external_file_id=external_id, name=f"Extra {index}.pdf",
                mime_type="application/pdf", source_url=f"https://drive.example.test/{external_id}",
                content_hash="hash", processing_version="v1", index_status="indexed",
            ))
            session.add(LibraryNode(
                organization_id=workspace.organization_id, source_id=UUID(source_id),
                parent_id=UUID(root["id"]), external_id=external_id, kind="file",
                name=f"Extra {index}.pdf", mime_type="application/pdf",
                source_url=f"https://drive.example.test/{external_id}",
            ))
        session.commit()

    provenance_queries: list[str] = []

    def count_provenance(_connection, _cursor, statement, _parameters, _context, _executemany):
        if "FROM documents" in statement and "JOIN workspace_folders" in statement:
            provenance_queries.append(statement)

    engine = factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", count_provenance)
    try:
        response = client.get(f"/library/nodes/{root['id']}/children?organization_id={organization}")
    finally:
        event.remove(engine, "before_cursor_execute", count_provenance)
    assert response.status_code == 200
    assert len(response.json()["items"]) == 13
    assert all(len(item["workspace_documents"]) == 1 for item in response.json()["items"])
    assert len(provenance_queries) == 1


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
    assert [item["query_status"] for item in contexts.json()["items"]] == ["no_indexed_content"]
    assert [item["status"] for item in syncs.json()["items"]] == ["syncing"]

    login(client, "outsider")
    outsider_org = client.post("/organizations", json={"name": "Other"}).json()["id"]
    forbidden = client.get(f"/library/search?organization_id={organization}&query=brief")
    own_empty = client.get(f"/library/syncs?organization_id={outsider_org}")
    assert forbidden.status_code == 403 and "Brief.pdf" not in forbidden.text
    assert own_empty.status_code == 200 and own_empty.json()["items"] == []


def _nest_file_under_folder(factory: sessionmaker[Session], organization: str, source_id: str) -> str:
    with factory() as session:
        root = session.query(LibraryNode).filter_by(kind="source").one()
        outer = LibraryNode(organization_id=UUID(organization), source_id=UUID(source_id), parent_id=root.id, external_id="outer", kind="folder", name="Outer")
        session.add(outer)
        session.flush()
        inner = LibraryNode(organization_id=UUID(organization), source_id=UUID(source_id), parent_id=outer.id, external_id="inner", kind="folder", name="Inner")
        session.add(inner)
        session.flush()
        session.query(LibraryNode).filter_by(kind="file", external_id="brief").one().parent_id = inner.id
        session.commit()
        return str(outer.id)


def test_admin_can_reprocess_and_remove_a_library_folder(api: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    source_id = seed_library(factory, organization)
    outer_id = _nest_file_under_folder(factory, organization, source_id)
    dispatched: list[UUID] = []
    client.app.state.ingestion_dispatcher = type("Dispatcher", (), {"dispatch": lambda self, job_id: dispatched.append(job_id)})()

    reprocess = client.post(f"/library/nodes/{outer_id}/reprocess?organization_id={organization}")
    assert reprocess.status_code == 202
    assert reprocess.json()["documents"] == 1 and len(reprocess.json()["job_ids"]) == 1
    assert len(dispatched) == 1
    with factory() as session:
        assert session.query(Document).one().content_hash == ""
        session.query(ProcessingJob).update({"status": ProcessingJobStatus.READY})
        session.commit()

    removed = client.delete(f"/library/nodes/{outer_id}/index?organization_id={organization}")
    assert removed.status_code == 200 and removed.json() == {"documents": 1}
    with factory() as session:
        assert session.query(Document).count() == 0

    file_node = client.post(f"/library/nodes/{source_id}/reprocess?organization_id={organization}")
    assert file_node.status_code == 403


@pytest.mark.parametrize("kind", ["folder", "source"])
def test_manual_recursive_run_persists_scope_progress_and_failures(api, kind):
    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    source = seed_library(factory, organization)
    outer = _nest_file_under_folder(factory, organization, source)
    root = client.get(f"/library?organization_id={organization}").json()["items"][0]
    node_id = outer if kind == "folder" else root["id"]
    dispatched = []
    client.app.state.ingestion_dispatcher = type("Dispatcher", (), {"dispatch": lambda self, job_id: dispatched.append(job_id)})()
    response = client.post(f"/library/nodes/{node_id}/reprocess?organization_id={organization}")
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    history = client.get(f"/library/manual-syncs?organization_id={organization}").json()["items"][0]
    assert history["id"] == run_id and history["scope_kind"] == kind
    assert history["scope_name"] == ("Outer" if kind == "folder" else "Google Drive")
    assert history["triggered_by"] == "member@example.test" and history["status"] == "queued"
    from app.ingestion.service import IngestionService
    with factory() as session:
        service = IngestionService(session)
        job = service.claim(job_id=dispatched[0])
        assert str(job.manual_run_id) == run_id
        session.commit()
        assert client.get(f"/library/manual-syncs?organization_id={organization}").json()["items"][0]["status"] == "syncing"
        service.apply_reconciliation(job_id=job.id, run_token=job.run_token, documents=[
            DiscoveredDocument("brief", "Brief.pdf", "application/pdf", "", text="text", parent_ids=("inner",)),
            DiscoveredDocument("new", "New.pdf", "application/pdf", "", error_code="download_failed", parent_ids=("new-inner",)),
            DiscoveredDocument("outside", "Outside.pdf", "application/pdf", "", text="outside", parent_ids=("root",)),
        ], manual_folders=[RemoteFolder("new-inner", "New Inner", ("inner",))])
        session.commit()
    history = client.get(f"/library/manual-syncs?organization_id={organization}").json()["items"][0]
    assert history["status"] == "partial_failure"
    assert history["total"] == history["processed"] == (2 if kind == "folder" else 3)
    assert history["failed"] == 1 and history["failures"][0]["name"] == "New.pdf"
    assert history["started_at"] and history["completed_at"]
    login(client, "outsider")
    assert client.get(f"/library/manual-syncs?organization_id={organization}").status_code == 403


def test_manual_source_queues_every_workspace_and_rebuilds_unchanged_chunks(api):
    from app.ingestion.service import IngestionService
    from app.knowledge.models import DocumentChunk
    from app.library.models import ManualSyncRun
    client, factory = api
    login(client)
    organization = client.post('/organizations', json={'name': 'Acme'}).json()['id']
    source = seed_library(factory, organization)
    root = client.get(f'/library?organization_id={organization}').json()['items'][0]
    with factory() as session:
        folder = session.query(WorkspaceFolder).one()
        service = IngestionService(session)
        initial = service.enqueue(scope=OrganizationScope(UUID(organization)), user_id=session.query(User).one().id, workspace_folder_id=folder.id)
        service.reconcile(job_id=initial.id, documents=[DiscoveredDocument('brief', 'Brief.pdf', 'application/pdf', '', text='identical text')])
        chunk_id = session.query(DocumentChunk).one().id
        other = WorkspaceFolder(organization_id=UUID(organization), source_id=UUID(source), external_folder_id='other', name='Other', uniform_access_confirmed=True, status='ready')
        session.add(other)
        session.commit()
    client.app.state.ingestion_dispatcher = type('Dispatcher', (), {'dispatch': lambda self, job_id: None})()
    response = client.post(f"/library/nodes/{root['id']}/reprocess?organization_id={organization}")
    assert response.status_code == 202 and len(response.json()['job_ids']) == 2
    with factory() as session:
        service = IngestionService(session)
        for job_id in response.json()['job_ids']:
            job = service.claim(job_id=UUID(job_id))
            # Restore the actual hash: explicit force must work independently of invalidation.
            document = session.query(Document).filter_by(workspace_folder_id=job.workspace_folder_id).first()
            if document:
                from hashlib import sha256
                document.content_hash = sha256(b'identical text').hexdigest()
            service.apply_reconciliation(job_id=job.id, run_token=job.run_token, documents=[DiscoveredDocument('brief', 'Brief.pdf', 'application/pdf', '', text='identical text')])
        session.commit()
        assert chunk_id not in [item.id for item in session.query(DocumentChunk).all()]
        run = session.get(ManualSyncRun, UUID(response.json()['run_id']))
        assert run.status == 'ready'
        for folder in session.query(WorkspaceFolder).all():
            service.remove_workspace(scope=OrganizationScope(UUID(organization)), user_id=session.query(User).one().id, workspace_folder_id=folder.id)
        session.commit()
    history = client.get(f'/library/manual-syncs?organization_id={organization}').json()['items'][0]
    assert history['status'] == 'ready' and history['total'] == history['processed'] == 1
    assert len(history['tasks']) == 2


def test_manual_queue_failure_is_persisted_and_active_run_cannot_be_reused(api):
    client, factory = api
    login(client)
    organization = client.post('/organizations', json={'name': 'Acme'}).json()['id']
    source = seed_library(factory, organization)
    outer = _nest_file_under_folder(factory, organization, source)
    class Dispatcher:
        def dispatch(self, job_id):
            raise RuntimeError('queue unavailable')
    client.app.state.ingestion_dispatcher = Dispatcher()
    assert client.post(f'/library/nodes/{outer}/reprocess?organization_id={organization}').status_code == 503
    history = client.get(f'/library/manual-syncs?organization_id={organization}').json()['items'][0]
    assert history['status'] == 'failed' and history['completed_at']
    assert history['tasks'][0]['error_code'] == 'sync_queue_unavailable'
    client.app.state.ingestion_dispatcher = type('Dispatcher', (), {'dispatch': lambda self, job_id: None})()
    assert client.post(f'/library/nodes/{outer}/reprocess?organization_id={organization}').status_code == 202
    assert client.post(f'/library/nodes/{outer}/reprocess?organization_id={organization}').status_code == 409
