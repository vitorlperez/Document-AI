import importlib
from collections.abc import Generator
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.audit_usage.models import AuditLog, SavedQuery
from app.core.config import Settings
from app.core.models import Base
from app.identity.auth import AuthenticationUnavailable, VerifiedIdentity
from app.identity.models import User
from app.ingestion.models import ProcessingJob, ProcessingJobStatus
from app.integrations.models import DataSource
from app.knowledge.models import Document, DocumentChunk
from app.organizations.models import Membership, MembershipRole
from app.workspaces.models import WorkspaceFolder, WorkspaceFolderSelection


class FakeAuthGateway:
    def __init__(self) -> None:
        self.identities: dict[str, VerifiedIdentity] = {}

    def authorization_url(self, *, state: str, screen_hint: str | None = None, max_age: int | None = None) -> str:
        return f"https://auth.example.test/login?state={state}"

    def exchange_code(self, *, code: str) -> VerifiedIdentity:
        try:
            return self.identities[code]
        except KeyError as error:
            raise AuthenticationUnavailable("invalid code") from error


class RecordingDispatcher:
    def __init__(self) -> None:
        self.job_ids: list[UUID] = []

    def dispatch(self, *, job_id: UUID) -> None:
        self.job_ids.append(job_id)


class UnavailableDispatcher:
    def dispatch(self, *, job_id: UUID) -> None:
        raise RuntimeError("queue unavailable")


@pytest.fixture()
def management_api(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[TestClient, sessionmaker[Session], FakeAuthGateway]]:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db")
    main = importlib.import_module("app.main")
    settings = Settings(
        database_url="postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db",
        public_app_url="http://app.example.test",
        environment="development",
    )
    app = main.create_app(settings)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    gateway = FakeAuthGateway()
    app.state.session_factory = factory
    app.state.auth_gateway = gateway
    with TestClient(app) as client:
        yield client, factory, gateway
    Base.metadata.drop_all(engine)
    engine.dispose()


def login(client: TestClient, gateway: FakeAuthGateway, *, code: str, email: str, subject: str) -> None:
    gateway.identities[code] = VerifiedIdentity(provider="workos", subject=subject, email=email)
    started = client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    response = client.get(f"/auth/callback?code={code}&state={state}", follow_redirects=False)
    assert response.status_code == 302


def create_organization(client: TestClient, *, name: str) -> UUID:
    response = client.post("/organizations", json={"name": name})
    assert response.status_code == 201
    return UUID(response.json()["id"])


def seed_folder(
    factory: sessionmaker[Session],
    *,
    organization_id: UUID,
    external_folder_id: str,
    with_local_data: bool = False,
) -> tuple[UUID, UUID, UUID | None]:
    with factory.begin() as session:
        user = session.query(User).filter_by(email="owner-a@example.test").one()
        source = session.query(DataSource).filter_by(organization_id=organization_id).one_or_none()
        if source is None:
            source = DataSource(
                organization_id=organization_id,
                provider="google_drive",
                encrypted_credentials="ciphertext",
                status="connected",
                connected_by_user_id=user.id,
            )
            session.add(source)
            session.flush()
        folder = WorkspaceFolder(
            organization_id=organization_id,
            source_id=source.id,
            external_folder_id=external_folder_id,
            name=external_folder_id,
            uniform_access_confirmed=True,
            status="ready",
        )
        session.add(folder)
        session.flush()
        if not with_local_data:
            return folder.id, source.id, None

        document = Document(
            organization_id=organization_id,
            workspace_folder_id=folder.id,
            external_file_id=f"{external_folder_id}-document",
            name=f"{external_folder_id}.pdf",
            mime_type="application/pdf",
            source_url=f"https://drive.example.test/{external_folder_id}",
            content_hash="a" * 64,
            processing_version="v1",
            index_status="indexed",
        )
        session.add(document)
        session.flush()
        session.add_all(
            [
                DocumentChunk(
                    organization_id=organization_id,
                    workspace_folder_id=folder.id,
                    document_id=document.id,
                    position=0,
                    text="Local indexed content.",
                    search_text="Local indexed content.",
                    embedding=[1.0, 0.0],
                    embedding_model="test",
                ),
                SavedQuery(
                    organization_id=organization_id,
                    workspace_folder_id=folder.id,
                    user_id=user.id,
                    name="Local query",
                    query="What is local?",
                    filters={},
                ),
                WorkspaceFolderSelection(
                    workspace_folder_id=folder.id,
                    kind="folder",
                    external_folder_id=external_folder_id,
                ),
                ProcessingJob(
                    organization_id=organization_id,
                    workspace_folder_id=folder.id,
                    idempotency_key=f"terminal-{external_folder_id}",
                    status=ProcessingJobStatus.READY,
                ),
            ]
        )
        return folder.id, source.id, document.id


def test_delete_folder_removes_its_local_graph_and_preserves_source_and_other_scope(management_api) -> None:
    client, factory, gateway = management_api
    login(client, gateway, code="owner-a", email="owner-a@example.test", subject="owner-a")
    organization_id = create_organization(client, name="Tenant A")
    removed_folder_id, source_id, removed_document_id = seed_folder(
        factory,
        organization_id=organization_id,
        external_folder_id="remove-me",
        with_local_data=True,
    )
    kept_folder_id, _, kept_document_id = seed_folder(
        factory,
        organization_id=organization_id,
        external_folder_id="keep-me",
        with_local_data=True,
    )

    response = client.delete(f"/workspace-folders/{removed_folder_id}?organization_id={organization_id}")

    assert response.status_code == 204
    with factory() as session:
        assert session.get(WorkspaceFolder, removed_folder_id) is None
        assert session.get(Document, removed_document_id) is None
        assert session.query(DocumentChunk).filter_by(workspace_folder_id=removed_folder_id).count() == 0
        assert session.query(SavedQuery).filter_by(workspace_folder_id=removed_folder_id).count() == 0
        assert session.query(WorkspaceFolderSelection).filter_by(workspace_folder_id=removed_folder_id).count() == 0
        assert session.query(ProcessingJob).filter_by(workspace_folder_id=removed_folder_id).count() == 0
        assert session.get(DataSource, source_id) is not None
        assert session.get(WorkspaceFolder, kept_folder_id) is not None
        assert session.get(Document, kept_document_id) is not None
        assert session.query(DocumentChunk).filter_by(workspace_folder_id=kept_folder_id).count() == 1
        assert session.query(AuditLog).filter_by(
            action="workspace_index.removed", target_id=removed_folder_id
        ).count() == 1


def test_delete_folder_denies_member_foreign_unknown_and_active_scope_without_mutation(management_api) -> None:
    client, factory, gateway = management_api
    login(client, gateway, code="owner-a", email="owner-a@example.test", subject="owner-a")
    organization_a = create_organization(client, name="Tenant A")
    folder_id, _, document_id = seed_folder(
        factory,
        organization_id=organization_a,
        external_folder_id="protected",
        with_local_data=True,
    )

    login(client, gateway, code="member-a", email="member-a@example.test", subject="member-a")
    with factory.begin() as session:
        member = session.query(User).filter_by(email="member-a@example.test").one()
        session.add(
            Membership(
                organization_id=organization_a,
                user_id=member.id,
                role=MembershipRole.MEMBER,
                is_active=True,
            )
        )
    member_response = client.delete(f"/workspace-folders/{folder_id}?organization_id={organization_a}")

    login(client, gateway, code="owner-b", email="owner-b@example.test", subject="owner-b")
    organization_b = create_organization(client, name="Tenant B")
    foreign_response = client.delete(f"/workspace-folders/{folder_id}?organization_id={organization_b}")

    login(client, gateway, code="owner-a", email="owner-a@example.test", subject="owner-a")
    unknown_response = client.delete(f"/workspace-folders/{uuid4()}?organization_id={organization_a}")
    with factory.begin() as session:
        session.add(
            ProcessingJob(
                organization_id=organization_a,
                workspace_folder_id=folder_id,
                idempotency_key="active-delete-guard",
                status=ProcessingJobStatus.QUEUED,
            )
        )
    active_response = client.delete(f"/workspace-folders/{folder_id}?organization_id={organization_a}")

    assert member_response.status_code == 403
    assert foreign_response.status_code == 403
    assert unknown_response.status_code == 403
    assert active_response.status_code == 409
    with factory() as session:
        assert session.get(WorkspaceFolder, folder_id) is not None
        assert session.get(Document, document_id) is not None
        assert session.query(DocumentChunk).filter_by(workspace_folder_id=folder_id).count() == 1
        assert session.query(AuditLog).filter_by(
            action="workspace_index.removed", target_id=folder_id
        ).count() == 0


def test_resync_enqueues_and_dispatches_only_the_requested_folder(management_api) -> None:
    client, factory, gateway = management_api
    dispatcher = RecordingDispatcher()
    client.app.state.ingestion_dispatcher = dispatcher
    login(client, gateway, code="owner-a", email="owner-a@example.test", subject="owner-a")
    organization_id = create_organization(client, name="Tenant A")
    target_folder_id, _, _ = seed_folder(
        factory, organization_id=organization_id, external_folder_id="target"
    )
    other_folder_id, _, _ = seed_folder(
        factory, organization_id=organization_id, external_folder_id="other"
    )

    response = client.post(f"/workspace-folders/{target_folder_id}/sync?organization_id={organization_id}")

    assert response.status_code == 202
    job_id = UUID(response.json()["job_id"])
    assert response.json()["status"] == ProcessingJobStatus.QUEUED.value
    assert dispatcher.job_ids == [job_id]
    with factory() as session:
        job = session.get(ProcessingJob, job_id)
        assert job is not None and job.workspace_folder_id == target_folder_id
        assert session.query(ProcessingJob).filter_by(workspace_folder_id=other_folder_id).count() == 0
        assert session.get(WorkspaceFolder, target_folder_id).status == ProcessingJobStatus.QUEUED.value
        assert session.get(WorkspaceFolder, other_folder_id).status == "ready"


def test_resync_denies_member_foreign_and_unknown_folders_without_enqueuing(management_api) -> None:
    client, factory, gateway = management_api
    dispatcher = RecordingDispatcher()
    client.app.state.ingestion_dispatcher = dispatcher
    login(client, gateway, code="owner-a", email="owner-a@example.test", subject="owner-a")
    organization_a = create_organization(client, name="Tenant A")
    folder_id, _, _ = seed_folder(factory, organization_id=organization_a, external_folder_id="protected")

    login(client, gateway, code="member-a", email="member-a@example.test", subject="member-a")
    with factory.begin() as session:
        member = session.query(User).filter_by(email="member-a@example.test").one()
        session.add(
            Membership(
                organization_id=organization_a,
                user_id=member.id,
                role=MembershipRole.MEMBER,
                is_active=True,
            )
        )
    member_response = client.post(f"/workspace-folders/{folder_id}/sync?organization_id={organization_a}")

    login(client, gateway, code="owner-b", email="owner-b@example.test", subject="owner-b")
    organization_b = create_organization(client, name="Tenant B")
    foreign_response = client.post(f"/workspace-folders/{folder_id}/sync?organization_id={organization_b}")

    login(client, gateway, code="owner-a", email="owner-a@example.test", subject="owner-a")
    unknown_response = client.post(f"/workspace-folders/{uuid4()}/sync?organization_id={organization_a}")

    assert member_response.status_code == 403
    assert foreign_response.status_code == 403
    assert unknown_response.status_code == 403
    assert dispatcher.job_ids == []
    with factory() as session:
        assert session.query(ProcessingJob).count() == 0
        assert session.get(WorkspaceFolder, folder_id).status == "ready"


def test_resync_queue_failure_returns_503_but_keeps_one_retryable_job(management_api) -> None:
    client, factory, gateway = management_api
    client.app.state.ingestion_dispatcher = UnavailableDispatcher()
    login(client, gateway, code="owner-a", email="owner-a@example.test", subject="owner-a")
    organization_id = create_organization(client, name="Tenant A")
    folder_id, _, _ = seed_folder(factory, organization_id=organization_id, external_folder_id="retryable")

    failed = client.post(f"/workspace-folders/{folder_id}/sync?organization_id={organization_id}")

    assert failed.status_code == 503
    with factory() as session:
        queued_job = session.query(ProcessingJob).filter_by(workspace_folder_id=folder_id).one()
        queued_job_id = queued_job.id
        assert queued_job.status is ProcessingJobStatus.QUEUED

    dispatcher = RecordingDispatcher()
    client.app.state.ingestion_dispatcher = dispatcher
    retried = client.post(f"/workspace-folders/{folder_id}/sync?organization_id={organization_id}")

    assert retried.status_code == 202
    assert UUID(retried.json()["job_id"]) == queued_job_id
    assert dispatcher.job_ids == [queued_job_id]
    with factory() as session:
        assert session.query(ProcessingJob).filter_by(workspace_folder_id=folder_id).count() == 1
