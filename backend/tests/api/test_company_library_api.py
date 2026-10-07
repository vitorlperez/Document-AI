import importlib
from collections.abc import Generator
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
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


def test_library_search_progressive_pages_include_results_beyond_old_limit(api):
    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    source_id = seed_library(factory, organization)
    root = client.get(f"/library?organization_id={organization}").json()["items"][0]
    with factory() as session:
        for index in range(105):
            session.add(LibraryNode(
                organization_id=UUID(organization), source_id=UUID(source_id),
                parent_id=UUID(root["id"]), external_id=f"progressive-{index}",
                kind="folder" if index < 3 else "file", name=f"Progressive {index:03d}",
            ))
        session.commit()
    batches = [client.get(
        f"/library/search?organization_id={organization}&query=progressive&page={page}&page_size=50"
    ).json() for page in range(1, 5)]
    assert [len(batch["items"]) for batch in batches] == [50, 50, 5, 0]
    assert all(batch["total"] == 105 and batch["pages"] == 3 for batch in batches)
    assert len({item["id"] for batch in batches for item in batch["items"]}) == 105
    assert [item["kind"] for item in batches[0]["items"][:3]] == ["folder"] * 3
    assert client.get(f"/library/search?organization_id={organization}&query=progressive&page=0").status_code == 422


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
    history = client.get(f"/library/manual-syncs?organization_id={organization}").json()["items"][0]
    assert history["mode"] == "incremental"
    assert reprocess.json()["documents"] == 1 and len(reprocess.json()["job_ids"]) == 1
    assert len(dispatched) == 1
    with factory() as session:
        # A resync keeps hashes: only changed content is rebuilt.
        assert session.query(Document).one().content_hash == "hash"
        session.query(ProcessingJob).update({"status": ProcessingJobStatus.READY})
        session.commit()
    everything = client.post(f"/library/nodes/{outer_id}/reprocess?organization_id={organization}&reprocess_all=true")
    assert everything.status_code == 202
    assert client.get(f"/library/manual-syncs?organization_id={organization}").json()["items"][0]["mode"] == "full"
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


def test_manual_source_queues_every_workspace_and_keeps_unchanged_chunks(api):
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
    response = client.post(f"/library/nodes/{root['id']}/reprocess?organization_id={organization}&reprocess_all=false")
    assert response.status_code == 202 and len(response.json()['job_ids']) == 2
    with factory() as session:
        service = IngestionService(session)
        for job_id in response.json()['job_ids']:
            job = service.claim(job_id=UUID(job_id))
            service.apply_reconciliation(job_id=job.id, run_token=job.run_token, documents=[DiscoveredDocument('brief', 'Brief.pdf', 'application/pdf', '', text='identical text')])
        session.commit()
        # Unchanged hash and processing version: the manual resync keeps the chunks.
        assert chunk_id in [item.id for item in session.query(DocumentChunk).all()]
        run = session.get(ManualSyncRun, UUID(response.json()['run_id']))
        assert run.status == 'ready'
        assert all(task['mode'] == 'incremental' for task in run.progress.values())
        for folder in session.query(WorkspaceFolder).all():
            service.remove_workspace(scope=OrganizationScope(UUID(organization)), user_id=session.query(User).one().id, workspace_folder_id=folder.id)
        session.commit()
    history = client.get(f'/library/manual-syncs?organization_id={organization}').json()['items'][0]
    assert history['status'] == 'ready' and history['total'] == history['processed'] == 1
    assert len(history['tasks']) == 2
    assert history['mode'] == 'incremental'


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
    first = client.post(f'/library/nodes/{outer}/reprocess?organization_id={organization}')
    assert first.status_code == 202
    # An incremental request while a sync is active follows that job instead of conflicting.
    second = client.post(f'/library/nodes/{outer}/reprocess?organization_id={organization}')
    assert second.status_code == 202 and second.json()['job_ids'] == first.json()['job_ids']
    # A complete resync still refuses to overlap an active job.
    assert client.post(f'/library/nodes/{outer}/reprocess?organization_id={organization}&reprocess_all=true').status_code == 409


@pytest.mark.parametrize("indexed", [True, False])
def test_remove_folder_removes_local_subtree_and_preserves_siblings(api, indexed):
    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    source = seed_library(factory, organization)
    outer = _nest_file_under_folder(factory, organization, source)
    with factory.begin() as session:
        root = session.query(LibraryNode).filter_by(kind="source").one()
        session.add(LibraryNode(organization_id=root.organization_id, source_id=root.source_id,
                                parent_id=root.id, external_id="sibling", kind="folder", name="Sibling"))
        if not indexed:
            session.query(Document).delete()
    removed = client.delete(f"/library/nodes/{outer}/index?organization_id={organization}")
    assert removed.status_code == 200
    assert removed.json() == {"documents": int(indexed)}
    children = client.get(f"/library/nodes/{root.id}/children?organization_id={organization}").json()["items"]
    assert [item["name"] for item in children] == ["Sibling"]
    assert client.get(f"/library/search?organization_id={organization}&query=Inner").json()["items"] == []
    with factory() as session:
        assert session.query(Document).count() == 0
        assert session.query(DataSource).one().status == "connected"
        assert session.query(WorkspaceFolder).count() == 1


def test_empty_folder_removal_requires_admin_and_rejects_active_sync(api):
    from app.ingestion.service import IngestionService
    from app.organizations.models import Membership, MembershipRole
    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    source = seed_library(factory, organization)
    outer = _nest_file_under_folder(factory, organization, source)
    with factory.begin() as session:
        session.query(Document).delete()
        session.query(Membership).one().role = MembershipRole.MEMBER
    assert client.delete(f"/library/nodes/{outer}/index?organization_id={organization}").status_code == 403
    with factory.begin() as session:
        session.query(Membership).one().role = MembershipRole.OWNER
        IngestionService(session).enqueue(scope=OrganizationScope(UUID(organization)),
            user_id=session.query(User).one().id, workspace_folder_id=session.query(WorkspaceFolder).one().id)
    assert client.delete(f"/library/nodes/{outer}/index?organization_id={organization}").status_code == 409
    with factory() as session:
        assert session.get(LibraryNode, UUID(outer)) is not None


def test_owner_can_disconnect_notion_and_preserve_knowledge(api):
    from datetime import UTC, datetime, timedelta

    from app.audit_usage.models import AuditLog
    from app.identity.auth import hash_secret
    from app.integrations.models import OAuthConnectionState
    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    source_id = seed_library(factory, organization)
    with factory.begin() as session:
        source = session.get(DataSource, UUID(source_id))
        source.provider = "notion"
        session.add(OAuthConnectionState(organization_id=source.organization_id,
            user_id=source.connected_by_user_id, source_id=source.id,
            session_hash=hash_secret("local"), state_hash=hash_secret("pending"),
            expires_at=datetime.now(UTC) + timedelta(minutes=10)))
    response = client.delete(f"/data-sources/{source_id}?organization_id={organization}")
    assert response.status_code == 204
    with factory() as session:
        source = session.get(DataSource, UUID(source_id))
        assert source.status == "disconnected" and source.encrypted_credentials is None
        assert session.query(Document).count() == session.query(WorkspaceFolder).count() == 1
        assert session.query(OAuthConnectionState).one().consumed_at is not None
        assert session.query(AuditLog).filter_by(action="data_source.disconnected").count() == 1


def test_history_contains_normal_sync_and_each_manual_resync_without_duplicates(api):
    from app.ingestion.service import IngestionService
    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    source = seed_library(factory, organization)
    outer = _nest_file_under_folder(factory, organization, source)
    root = client.get(f"/library?organization_id={organization}").json()["items"][0]
    client.app.state.ingestion_dispatcher = type("Dispatcher", (), {"dispatch": lambda self, job_id: None})()
    with factory() as session:
        workspace_id = str(session.query(WorkspaceFolder).one().id)
    normal = client.post(f"/workspace-folders/{workspace_id}/sync?organization_id={organization}")
    assert normal.status_code == 202
    with factory.begin() as session:
        IngestionService(session).reconcile(job_id=UUID(normal.json()["job_id"]), documents=[
            DiscoveredDocument("brief", "Brief.pdf", "application/pdf", "", text="body", parent_ids=("inner",))])
    manual_ids = []
    for path in [f"nodes/{outer}", f"nodes/{root['id']}", f"workspaces/{workspace_id}"]:
        response = client.post(f"/library/{path}/reprocess?organization_id={organization}")
        assert response.status_code == 202
        manual_ids.append(response.json()["run_id"])
        with factory.begin() as session:
            for job in session.query(ProcessingJob).filter_by(manual_run_id=UUID(manual_ids[-1])):
                IngestionService(session).reconcile(job_id=job.id, documents=[
                    DiscoveredDocument("brief", "Brief.pdf", "application/pdf", "", text="body", parent_ids=("inner",))])
        # Each newly completed run remains separately visible after a fresh GET.
        history = client.get(f"/library/sync-history?organization_id={organization}")
        assert history.status_code == 200
        ids = [item["id"] for item in history.json()["items"]]
        assert set(manual_ids + [normal.json()["job_id"]]) == set(ids)
        assert len(ids) == len(set(ids))
        assert ids[0] == manual_ids[-1]
    assert {item["operation"] for item in history.json()["items"]} == {"sync", "resync"}
    assert all(item["status"] == "ready" for item in history.json()["items"])
    login(client, "outsider")
    assert client.get(f"/library/sync-history?organization_id={organization}").status_code == 403


def test_normal_sync_history_survives_workspace_deletion_and_is_not_forced(api):
    from app.ingestion.service import IngestionService
    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    seed_library(factory, organization)
    client.app.state.ingestion_dispatcher = type("Dispatcher", (), {"dispatch": lambda self, job_id: None})()
    with factory() as session:
        workspace_id = str(session.query(WorkspaceFolder).one().id)
    result = client.post(f"/workspace-folders/{workspace_id}/sync?organization_id={organization}").json()
    with factory.begin() as session:
        service = IngestionService(session)
        job = session.get(ProcessingJob, UUID(result["job_id"]))
        assert job.manual_run_id is None
        service.reconcile(job_id=job.id, documents=[DiscoveredDocument("brief", "Brief.pdf", "application/pdf", "", text="body")])
        service.remove_workspace(scope=OrganizationScope(UUID(organization)),
            user_id=session.query(User).one().id, workspace_folder_id=UUID(workspace_id))
    history = client.get(f"/library/sync-history?organization_id={organization}").json()["items"]
    assert len(history) == 1
    assert history[0]["id"] == result["job_id"]
    assert history[0]["operation"] == "sync" and history[0]["status"] == "ready"
    assert history[0]["triggered_by"] == "member@example.test"
    assert history[0]["total"] == history[0]["processed"] == 1


@pytest.mark.parametrize("role", ["member", "inactive", "outsider"])
def test_notion_disconnect_rejects_unauthorized_users(api, role):
    from app.organizations.models import Membership, MembershipRole
    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    source_id = seed_library(factory, organization)
    with factory.begin() as session:
        session.get(DataSource, UUID(source_id)).provider = "notion"
        if role == "member": session.query(Membership).one().role = MembershipRole.MEMBER
        if role == "inactive": session.query(Membership).one().is_active = False
    if role == "outsider": login(client, "outsider")
    assert client.delete(f"/data-sources/{source_id}?organization_id={organization}").status_code == 403
    with factory() as session:
        source = session.get(DataSource, UUID(source_id))
        assert source.status == "connected" and source.encrypted_credentials == "encrypted"


def test_scheduler_and_legacy_jobs_are_visible_once_in_history(api):
    from app.ingestion.service import IngestionService
    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    seed_library(factory, organization)
    with factory.begin() as session:
        folder = session.query(WorkspaceFolder).one()
        legacy = ProcessingJob(organization_id=folder.organization_id, workspace_folder_id=folder.id,
            idempotency_key="legacy-history", status=ProcessingJobStatus.READY)
        session.add(legacy)
        service = IngestionService(session)
        job = service.enqueue_system(scope=OrganizationScope(UUID(organization)), workspace_folder_id=folder.id)
        assert service.enqueue_system(scope=OrganizationScope(UUID(organization)), workspace_folder_id=folder.id).id == job.id
        service.fail(job_id=job.id, error_code="sync_queue_unavailable")
        legacy_id, scheduled_id = str(legacy.id), str(job.id)
    items = client.get(f"/library/sync-history?organization_id={organization}").json()["items"]
    assert len(items) == 2 and {item["id"] for item in items} == {legacy_id, scheduled_id}
    scheduled = next(item for item in items if item["id"] == scheduled_id)
    assert scheduled["triggered_by"] == "Agendamento automático"
    assert scheduled["status"] == "failed" and scheduled["completed_at"]
    assert scheduled["tasks"][0]["error_code"] == "sync_queue_unavailable"
    old = next(item for item in items if item["id"] == legacy_id)
    assert old["total"] is None and old["triggered_by"] is None


@pytest.mark.parametrize("kind", ["file", "folder"])
@pytest.mark.parametrize("sync_mode", ["normal", "scheduled", "resync"])
def test_library_removal_persists_across_discovery_and_reprocessing(api, kind, sync_mode):
    from app.ingestion.service import IngestionService
    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    source_id = seed_library(factory, organization)
    outer_id = _nest_file_under_folder(factory, organization, source_id)
    root = client.get(f"/library?organization_id={organization}").json()["items"][0]
    with factory() as session:
        document = session.query(Document).one()
        workspace_id, document_id = str(document.workspace_folder_id), str(document.id)
    if kind == "folder":
        removed = client.delete(f"/library/nodes/{outer_id}/index?organization_id={organization}")
        assert removed.status_code == 200
    else:
        removed = client.delete(f"/workspace-folders/{workspace_id}/documents/{document_id}?organization_id={organization}")
        assert removed.status_code == 204
    # A fresh API session must see the item disappear from browse and name search.
    assert client.get(f"/library/search?organization_id={organization}&query=Brief").json()["items"] == []
    with factory() as session:
        assert session.query(LibraryNode).filter_by(external_id="brief").count() == 0
        if kind == "folder":
            assert session.query(LibraryNode).filter(LibraryNode.kind != "source").count() == 0
    client.app.state.ingestion_dispatcher = type("Dispatcher", (), {"dispatch": lambda self, job_id: None})()
    if sync_mode == "resync":
        response = client.post(f"/library/nodes/{root['id']}/reprocess?organization_id={organization}")
        assert response.status_code == 202
        job_id = UUID(response.json()["job_ids"][0])
    elif sync_mode == "normal":
        response = client.post(f"/workspace-folders/{workspace_id}/sync?organization_id={organization}")
        assert response.status_code == 202
        job_id = UUID(response.json()["job_id"])
    else:
        with factory.begin() as session:
            job_id = IngestionService(session).enqueue_system(scope=OrganizationScope(UUID(organization)),
                workspace_folder_id=UUID(workspace_id)).id
    documents = [
        DiscoveredDocument("brief", "Brief.pdf", "application/pdf", "", text="remote unchanged", parent_ids=("inner",)),
        DiscoveredDocument("new-child", "New Child.pdf", "application/pdf", "", text="new remote child", parent_ids=("new-inner",)),
        DiscoveredDocument("safe", "Safe.pdf", "application/pdf", "", text="unrelated file"),
    ]
    folders = [RemoteFolder("outer", "Outer"), RemoteFolder("inner", "Inner", ("outer",)),
               RemoteFolder("new-inner", "New Inner", ("inner",))]
    # Re-open a session: exclusions must be persisted, not an in-memory UI filter.
    with factory.begin() as session:
        service = IngestionService(session)
        job = service.claim(job_id=job_id)
        service.apply_reconciliation(job_id=job.id, run_token=job.run_token,
            documents=documents, manual_folders=folders)
        LibraryService(session).project_successful_sync(organization_id=UUID(organization),
            source=session.get(DataSource, UUID(source_id)), documents=documents, folders=folders)
    assert client.get(f"/library/search?organization_id={organization}&query=Brief").json()["items"] == []
    with factory() as session:
        assert session.query(Document).filter_by(external_file_id="brief").count() == 0
        assert session.query(LibraryNode).filter_by(external_id="brief").count() == 0
        assert session.get(DataSource, UUID(source_id)).encrypted_credentials == "encrypted"
        assert session.query(Document).filter_by(external_file_id="safe").one().index_status == "indexed"
        if kind == "folder":
            assert {node.external_id for node in session.query(LibraryNode)} == {root["external_id"], "safe"}
            assert session.query(Document).filter_by(external_file_id="new-child").count() == 0
            for query in ["Outer", "Inner", "Child"]:
                assert client.get(f"/library/search?organization_id={organization}&query={query}").json()["items"] == []


@pytest.mark.parametrize("kind", ["source", "folder"])
def test_resync_without_sync_workspace_returns_clear_error_and_no_run(api, kind):
    from app.library.models import ManualSyncRun

    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    source_id = seed_library(factory, organization)
    with factory.begin() as session:
        source = session.get(DataSource, UUID(source_id))
        LibraryService(session).project_successful_sync(
            organization_id=UUID(organization), source=source, documents=[],
            folders=[RemoteFolder("unsynced", "Unsynced")],
        )
        session.query(Document).filter_by(organization_id=UUID(organization)).delete()
        session.query(WorkspaceFolder).filter_by(organization_id=UUID(organization)).delete()
        node_id = session.query(LibraryNode).filter_by(source_id=UUID(source_id), kind=kind).one().id
    response = client.post(f"/library/nodes/{node_id}/reprocess?organization_id={organization}")
    assert response.status_code == 400
    assert "espaço sincronizado" in response.json()["detail"]
    with factory() as session:
        assert session.query(ManualSyncRun).count() == 0
        assert session.query(ProcessingJob).count() == 0


def test_production_click_sequence_is_visible_in_history_while_running_and_after_removal(api):
    """Replays the production timeline of 2026-09-30 02:59-03:09 UTC.

    A tool resync (POST /library/nodes/{root}/reprocess) was followed by syncs
    triggered from the integration screen (POST /workspace-folders/{id}/sync)
    and by the removal of those workspaces. The modal only read manual runs, so
    the integration syncs never had an entry or progress to show.
    """
    from app.ingestion.service import IngestionService
    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    seed_library(factory, organization)
    root = client.get(f"/library?organization_id={organization}").json()["items"][0]
    client.app.state.ingestion_dispatcher = type("Dispatcher", (), {"dispatch": lambda self, job_id: None})()
    with factory() as session:
        workspace_id = str(session.query(WorkspaceFolder).one().id)

    def history() -> dict[str, dict]:
        response = client.get(f"/library/sync-history?organization_id={organization}")
        assert response.status_code == 200
        return {item["id"]: item for item in response.json()["items"]}

    def finish(job_id: str) -> None:
        with factory.begin() as session:
            IngestionService(session).reconcile(job_id=UUID(job_id), documents=[
                DiscoveredDocument("brief", "Brief.pdf", "application/pdf", "", text="body")])

    tool = client.post(f"/library/nodes/{root['id']}/reprocess?organization_id={organization}")
    assert tool.status_code == 202
    queued = history()[tool.json()["run_id"]]
    # The click must be visible right away, with a task whose progress can be followed.
    assert queued["operation"] == "resync" and queued["status"] == "queued"
    assert [task["workspace_folder_id"] for task in queued["tasks"]] == [workspace_id]
    finish(tool.json()["job_ids"][0])
    assert history()[tool.json()["run_id"]]["status"] == "ready"

    integration_sync = client.post(f"/workspace-folders/{workspace_id}/sync?organization_id={organization}")
    assert integration_sync.status_code == 202
    job_id = integration_sync.json()["job_id"]
    running = history()[job_id]
    assert running["operation"] == "sync" and running["status"] == "queued"
    assert running["triggered_by"] == "member@example.test"
    finish(job_id)
    done = history()[job_id]
    assert done["status"] == "ready" and done["total"] == done["processed"] == 1

    assert client.delete(f"/workspace-folders/{workspace_id}?organization_id={organization}").status_code == 204
    # Removing the workspace deletes its jobs; the history snapshots must remain.
    assert set(history()) == {tool.json()["run_id"], job_id}


def test_notion_catalog_exposes_page_hierarchy_and_saves_provider_specific_scope_name(api, monkeypatch):
    from types import SimpleNamespace

    from app.api import integrations

    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    source_id = seed_library(factory, organization)
    with factory.begin() as session:
        session.get(DataSource, UUID(source_id)).provider = "notion"
    rows = [RemoteFolder("parent", "Parent", kind="page"),
            RemoteFolder("child", "Child", ("parent",), kind="page"),
            RemoteFolder("db", "Projects", ("parent",), kind="database")]
    monkeypatch.setattr(integrations, "IntegrationRegistry", lambda _: SimpleNamespace(
        get=lambda _: SimpleNamespace(folders=lambda **_: rows)))
    catalog = client.get(f"/data-sources/{source_id}/scope-catalog?organization_id={organization}")
    assert catalog.status_code == 200
    assert catalog.json()["folders"][1] == {"id": "child", "name": "Child", "parent_ids": ["parent"], "kind": "page"}
    selected = client.post(f"/workspace-folders/selections?organization_id={organization}", json={
        "source_id": source_id, "mode": "all_accessible", "uniform_access_confirmed": True,
    })
    assert selected.status_code == 201
    with factory() as session:
        workspace = session.get(WorkspaceFolder, UUID(selected.json()["id"]))
        assert workspace.name == "Todas as páginas acessíveis do Notion"


def test_sync_status_is_member_safe_and_reports_committed_partial_content(api):

    from app.ingestion.service import IngestionService
    from app.knowledge.models import DocumentChunk
    from app.knowledge.questions import EMBEDDING_MODEL
    from app.library.manual_sync import update_progress
    from app.organizations.models import Membership, MembershipRole

    client, factory = api
    login(client)
    organization_id = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    source_id = seed_library(factory, organization_id)
    with factory.begin() as session:
        member = session.scalar(select(Membership))
        member.role = MembershipRole.MEMBER
        folder = session.scalar(select(WorkspaceFolder))
        # Ordinary scheduled job: no manual_run_id; it still publishes progress.
        job = IngestionService(session).enqueue_system(scope=OrganizationScope(UUID(organization_id)),
                                                       workspace_folder_id=folder.id)
        IngestionService(session).claim(job_id=job.id)
        folder.status = "syncing"
        document = session.scalar(select(Document))
        session.add(DocumentChunk(organization_id=UUID(organization_id), workspace_folder_id=folder.id,
                                  document_id=document.id, position=0, text="Approved scope",
                                  search_text="Approved scope", embedding=[1.0, 1.0],
                                  embedding_model=EMBEDDING_MODEL))
        update_progress(session, job, stage="embedding", processed=1, total=3)
    response = client.get(f"/library/sync-status?organization_id={organization_id}")
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert set(item) == {"source_id", "provider", "library_node_id", "state", "stage", "processed",
                         "total", "failed", "skipped", "queryable", "started_at", "last_synced_at",
                         "error_code"}
    root = client.get(f"/library?organization_id={organization_id}").json()["items"][0]
    assert item["source_id"] == source_id and item["library_node_id"] == root["id"]
    assert (item["state"], item["stage"], item["processed"], item["total"], item["failed"], item["queryable"]) == (
        "syncing", "embedding", 1, 3, 0, True)
    assert item["started_at"] and item["error_code"] is None
    assert "encrypted" not in response.text and "member@example.test" not in response.text
    context = client.get(f"/library/question-contexts?organization_id={organization_id}").json()["items"][0]
    assert context["sync_in_progress"] is True and context["query_status"] == "ready"
    login(client, "outsider")
    assert client.get(f"/library/sync-status?organization_id={organization_id}").status_code == 403


@pytest.mark.parametrize("provider, expected", [("notion", "notion"), ("google", "google_drive")])
def test_sync_status_connected_tool_without_library_root_is_idle(api, provider, expected):
    client, factory = api
    login(client)
    organization_id = client.post("/organizations", json={"name": "Empty"}).json()["id"]
    with factory.begin() as session:
        user = session.scalar(select(User))
        source = DataSource(organization_id=UUID(organization_id), provider=provider,
                            encrypted_credentials="secret", status="connected", connected_by_user_id=user.id)
        session.add(source)
    response = client.get(f"/library/sync-status?organization_id={organization_id}")
    assert response.status_code == 200
    assert response.json()["items"] == [{
        "source_id": str(source.id), "provider": expected, "library_node_id": None,
        "state": "idle", "stage": None, "processed": 0, "total": 0, "failed": 0, "skipped": 0,
        "queryable": False, "started_at": None, "last_synced_at": None, "error_code": None,
    }]


def test_sync_history_and_status_report_empty_files_as_skipped(api):
    from app.ingestion.service import IngestionService
    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    seed_library(factory, organization)
    client.app.state.ingestion_dispatcher = type("Dispatcher", (), {"dispatch": lambda self, job_id: None})()
    with factory() as session:
        workspace_id = str(session.query(WorkspaceFolder).one().id)
    result = client.post(f"/workspace-folders/{workspace_id}/sync?organization_id={organization}").json()
    with factory.begin() as session:
        IngestionService(session).reconcile(job_id=UUID(result["job_id"]), documents=[
            DiscoveredDocument("brief", "Brief.pdf", "application/pdf", "", text="body"),
            DiscoveredDocument("blank", "Untitled", "application/vnd.google-apps.document", "", text=""),
        ])
    run = client.get(f"/library/sync-history?organization_id={organization}").json()["items"][0]
    assert (run["status"], run["total"], run["processed"], run["failed"], run["failures"]) == ("ready", 2, 2, 0, [])
    assert run["skipped"] == 1
    assert run["skipped_items"] == [{"external_id": "blank", "name": "Untitled", "reason": "empty_content"}]
    item = client.get(f"/library/sync-status?organization_id={organization}").json()["items"][0]
    assert (item["state"], item["processed"], item["total"], item["failed"], item["skipped"]) == ("ready", 2, 2, 0, 1)


def _clickup_source(factory, organization: str) -> str:
    source_id = seed_library(factory, organization)
    with factory.begin() as session:
        session.get(DataSource, UUID(source_id)).provider = "clickup"
    return source_id


def _fake_clickup_registry(monkeypatch, *, rows=None, error=None):
    from types import SimpleNamespace

    from app.api import integrations

    def folders(**_):
        if error is not None:
            raise error
        return rows

    monkeypatch.setattr(integrations, "IntegrationRegistry", lambda _: SimpleNamespace(
        get=lambda _: SimpleNamespace(folders=folders)))


def test_clickup_catalog_exposes_the_hierarchy_and_saves_a_folder_scope(api, monkeypatch):
    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    source_id = _clickup_source(factory, organization)
    _fake_clickup_registry(monkeypatch, rows=[
        RemoteFolder("clickup:workspace:w", "Acme", kind="workspace"),
        RemoteFolder("clickup:space:s", "Projetos", ("clickup:workspace:w",), kind="space"),
        RemoteFolder("clickup:list:l", "Contratos", ("clickup:space:s",), kind="list")])
    catalog = client.get(f"/data-sources/{source_id}/scope-catalog?organization_id={organization}")
    assert catalog.status_code == 200
    assert catalog.json()["folders"][2] == {"id": "clickup:list:l", "name": "Contratos", "kind": "list",
                                           "parent_ids": ["clickup:space:s"]}
    assert catalog.json()["root_files"]["available"] is False
    assert catalog.json()["all_accessible"]["available"] is True
    selected = client.post(f"/workspace-folders/selections?organization_id={organization}", json={
        "source_id": source_id, "mode": "selected", "folder_ids": ["clickup:space:s"],
        "uniform_access_confirmed": True,
    })
    assert selected.status_code == 201
    unknown = client.post(f"/workspace-folders/selections?organization_id={organization}", json={
        "source_id": source_id, "mode": "selected", "folder_ids": ["clickup:list:elsewhere"],
        "uniform_access_confirmed": True,
    })
    assert unknown.status_code == 422
    with factory() as session:
        workspace = session.get(WorkspaceFolder, UUID(selected.json()["id"]))
        assert workspace.name == "Projetos"


@pytest.mark.parametrize("role", ["member", "inactive", "outsider"])
def test_clickup_catalog_and_selection_reject_non_admins(api, monkeypatch, role):
    from app.organizations.models import Membership, MembershipRole
    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    source_id = _clickup_source(factory, organization)
    _fake_clickup_registry(monkeypatch, rows=[RemoteFolder("clickup:list:l", "Contratos", kind="list")])
    with factory.begin() as session:
        if role == "member": session.query(Membership).one().role = MembershipRole.MEMBER
        if role == "inactive": session.query(Membership).one().is_active = False
    if role == "outsider": login(client, "outsider")
    assert client.get(f"/data-sources/{source_id}/scope-catalog?organization_id={organization}").status_code in {403, 404}
    response = client.post(f"/workspace-folders/selections?organization_id={organization}", json={
        "source_id": source_id, "mode": "all_accessible", "uniform_access_confirmed": True,
    })
    assert response.status_code in {403, 404}
    with factory() as session:
        assert session.query(WorkspaceFolder).filter_by(source_id=UUID(source_id)).count() == 1  # seeded scope only


@pytest.mark.parametrize("failure", ["unauthorized", "forbidden"])
def test_clickup_revoked_token_asks_for_reconnection_instead_of_failing(api, monkeypatch, failure):
    from app.integrations.clickup import ClickUpRemoteUnauthorized
    from app.integrations.errors import SourceItemUnavailable
    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    source_id = _clickup_source(factory, organization)
    _fake_clickup_registry(monkeypatch, error=ClickUpRemoteUnauthorized() if failure == "unauthorized" else SourceItemUnavailable("restricted_resource"))
    response = client.get(f"/data-sources/{source_id}/scope-catalog?organization_id={organization}")
    assert response.status_code == 409 and response.json() == {"detail": "reauthentication required"}
    with factory() as session:
        assert session.get(DataSource, UUID(source_id)).status == "reauth_required"


def test_clickup_disconnect_is_admin_only_and_clears_the_credentials(api):
    from app.organizations.models import Membership, MembershipRole
    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    source_id = _clickup_source(factory, organization)
    with factory.begin() as session:
        session.query(Membership).one().role = MembershipRole.MEMBER
    assert client.delete(f"/data-sources/{source_id}?organization_id={organization}").status_code == 403
    with factory.begin() as session:
        session.query(Membership).one().role = MembershipRole.OWNER
    assert client.delete(f"/data-sources/{source_id}?organization_id={organization}").status_code == 204
    with factory() as session:
        source = session.get(DataSource, UUID(source_id))
        assert (source.status, source.encrypted_credentials) == ("disconnected", None)


def test_clickup_oauth_start_requires_configuration(api):
    client, _ = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    response = client.get(f"/data-sources/clickup/oauth/start?organization_id={organization}", follow_redirects=False)
    assert response.status_code == 503 and response.json() == {"detail": "integration unavailable"}


def test_clickup_oauth_round_trip_stores_only_encrypted_credentials(api, monkeypatch):
    import httpx
    from cryptography.fernet import Fernet
    from pydantic import SecretStr
    client, factory = api
    settings = client.app.state.settings
    key = Fernet.generate_key().decode()
    for name, value in {"clickup_oauth_client_id": "cid", "clickup_oauth_client_secret": SecretStr("csecret"),
                        "clickup_oauth_redirect_uri": "http://api.example.test/data-sources/clickup/oauth/callback",
                        "clickup_token_encryption_key": SecretStr(key)}.items():
        monkeypatch.setattr(settings, name, value)
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    started = client.get(f"/data-sources/clickup/oauth/start?organization_id={organization}", follow_redirects=False)
    assert started.status_code == 302
    assert started.headers["location"].startswith("https://app.clickup.com/api?")
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    monkeypatch.setattr(httpx, "post", lambda url, **kw: httpx.Response(
        200, json={"access_token": "clickup-secret-token"}, request=httpx.Request("POST", url)))
    monkeypatch.setattr(httpx, "get", lambda url, **kw: httpx.Response(
        200, json={"user": {"email": "Owner@Example.Test"}}, request=httpx.Request("GET", url)))
    done = client.get(f"/data-sources/clickup/oauth/callback?code=the-code&state={state}",
                      headers={"accept": "text/html"}, follow_redirects=False)
    assert done.status_code == 303
    assert done.headers["location"] == f"http://app.example.test/companies/{organization}/integrations?connected=clickup"
    assert "the-code" not in done.headers["location"] and state not in done.headers["location"]
    with factory() as session:
        source = session.scalar(select(DataSource).where(DataSource.provider == "clickup"))
        assert (source.status, source.account_email) == ("connected", "owner@example.test")
        assert source.encrypted_credentials and "clickup-secret-token" not in source.encrypted_credentials
    replay = client.get(f"/data-sources/clickup/oauth/callback?code=the-code&state={state}")
    assert replay.status_code == 401
