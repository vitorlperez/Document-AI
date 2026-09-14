from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.audit_usage.models import UsageRecord
from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.ingestion.service import DiscoveredDocument, IngestionService
from app.integrations.models import DataSource
from app.knowledge.models import DocumentChunk
from app.knowledge.questions import (
    EMBEDDING_MODEL,
    AIProviderRateLimited,
    AIProviderUnavailable,
    EmbeddingService,
)
from app.organizations.models import Membership, MembershipRole, Organization
from app.workspaces.models import WorkspaceFolder


class FakeEmbeddingProvider:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.calls: list[list[str]] = []

    def embed(self, *, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        if self.fail:
            raise AIProviderUnavailable("provider unavailable")
        return [[float(index + 1), 1.0] for index, _ in enumerate(texts)]

    def answer(self, *, question: str, evidence):  # pragma: no cover - protocol test double
        raise AssertionError("ingestion must not generate an answer")


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as database_session:
        yield database_session
    Base.metadata.drop_all(engine)
    engine.dispose()


def workspace(session: Session) -> tuple[Organization, User, WorkspaceFolder]:
    organization = Organization(name="Acme")
    user = User(email=f"admin-{uuid4()}@example.test")
    session.add_all([organization, user])
    session.flush()
    session.add(Membership(organization_id=organization.id, user_id=user.id, role=MembershipRole.ADMIN, is_active=True))
    source = DataSource(
        organization_id=organization.id,
        provider="google_drive",
        encrypted_credentials="ciphertext",
        status="connected",
        connected_by_user_id=user.id,
    )
    session.add(source)
    session.flush()
    folder = WorkspaceFolder(
        organization_id=organization.id,
        source_id=source.id,
        external_folder_id="folder-1",
        name="Client A",
        uniform_access_confirmed=True,
    )
    session.add(folder)
    session.commit()
    return organization, user, folder


def document(text: str, *, name: str = "Briefing.pdf") -> DiscoveredDocument:
    return DiscoveredDocument(
        external_file_id="briefing-1",
        name=name,
        mime_type="application/pdf",
        source_url="https://drive.example.test/briefing-1",
        text=text,
    )


def stage_sync(session: Session, organization: Organization, user: User, folder: WorkspaceFolder, documents: list[DiscoveredDocument]):
    service = IngestionService(session)
    job = service.enqueue(scope=OrganizationScope(organization.id), user_id=user.id, workspace_folder_id=folder.id)
    claimed = service.claim(job_id=job.id)
    assert claimed is not None and claimed.run_token is not None
    session.commit()
    staged = service.apply_reconciliation(job_id=job.id, run_token=claimed.run_token, documents=documents, finalize=False)
    assert staged is not None
    return service, job, claimed.run_token


def finish_sync(service: IngestionService, job_id, run_token: str, documents: list[DiscoveredDocument]):
    return service.finalize_reconciliation(
        job_id=job_id,
        run_token=run_token,
        partial_failure=any(item.error_code or not item.text or not item.text.strip() for item in documents),
    )


def test_new_chunks_are_embedded_before_the_sync_is_ready(session: Session) -> None:
    organization, user, folder = workspace(session)
    discovered = [document("a" * 1201)]
    service, job, run_token = stage_sync(session, organization, user, folder, discovered)
    provider = FakeEmbeddingProvider()

    embedded = EmbeddingService(session, provider).embed_workspace(
        scope=OrganizationScope(organization.id), workspace_folder_id=folder.id
    )

    assert embedded == 2
    assert job.status.value == "syncing"
    assert folder.status == "syncing"
    chunks = list(session.scalars(select(DocumentChunk).order_by(DocumentChunk.position)))
    assert [chunk.embedding_model for chunk in chunks] == [EMBEDDING_MODEL, EMBEDDING_MODEL]
    assert all(chunk.embedding is not None for chunk in chunks)
    assert provider.calls == [[chunk.text for chunk in chunks]]
    completed = finish_sync(service, job.id, run_token, discovered)
    assert completed is not None and completed.status.value == "ready"
    assert folder.status == "ready"


def test_unchanged_documents_keep_vectors_and_do_not_reembed(session: Session) -> None:
    organization, user, folder = workspace(session)
    first_provider = FakeEmbeddingProvider()
    first_documents = [document("An approved delivery scope.")]
    service, job, run_token = stage_sync(session, organization, user, folder, first_documents)
    EmbeddingService(session, first_provider).embed_workspace(
        scope=OrganizationScope(organization.id), workspace_folder_id=folder.id
    )
    finish_sync(service, job.id, run_token, first_documents)
    session.commit()
    original = session.scalar(select(DocumentChunk))
    assert original is not None
    original_id, original_vector = original.id, original.embedding

    second_provider = FakeEmbeddingProvider()
    service, next_job, next_token = stage_sync(session, organization, user, folder, first_documents)
    embedded = EmbeddingService(session, second_provider).embed_workspace(
        scope=OrganizationScope(organization.id), workspace_folder_id=folder.id
    )
    finish_sync(service, next_job.id, next_token, first_documents)

    current = session.scalar(select(DocumentChunk))
    assert embedded == 0 and second_provider.calls == []
    assert current is not None and (current.id, current.embedding) == (original_id, original_vector)


def test_outdated_embedding_model_is_refreshed_with_the_current_model(session: Session) -> None:
    organization, user, folder = workspace(session)
    discovered = [document("A document requiring a vector refresh.")]
    service, job, run_token = stage_sync(session, organization, user, folder, discovered)
    EmbeddingService(session, FakeEmbeddingProvider()).embed_workspace(
        scope=OrganizationScope(organization.id), workspace_folder_id=folder.id
    )
    finish_sync(service, job.id, run_token, discovered)
    session.commit()
    existing = session.scalar(select(DocumentChunk))
    assert existing is not None
    existing.embedding_model = "legacy-model"
    session.commit()

    provider = FakeEmbeddingProvider()
    refreshed = EmbeddingService(session, provider).embed_workspace(
        scope=OrganizationScope(organization.id), workspace_folder_id=folder.id
    )

    assert refreshed == 1 and provider.calls == [[existing.text]]
    assert existing.embedding_model == EMBEDDING_MODEL


def test_embedding_failure_rolls_back_new_snapshot_and_keeps_old_documents_searchable(session: Session) -> None:
    organization, user, folder = workspace(session)
    old_documents = [document("The old approved scope.")]
    service, job, run_token = stage_sync(session, organization, user, folder, old_documents)
    EmbeddingService(session, FakeEmbeddingProvider()).embed_workspace(
        scope=OrganizationScope(organization.id), workspace_folder_id=folder.id
    )
    finish_sync(service, job.id, run_token, old_documents)
    session.commit()
    old_chunk = session.scalar(select(DocumentChunk))
    assert old_chunk is not None
    old_chunk_id, old_text, old_vector = old_chunk.id, old_chunk.text, old_chunk.embedding

    changed_documents = [document("The replacement scope must not leak after failure.")]
    service, failed_job, failed_token = stage_sync(session, organization, user, folder, changed_documents)
    with pytest.raises(AIProviderUnavailable):
        EmbeddingService(session, FakeEmbeddingProvider(fail=True)).embed_workspace(
            scope=OrganizationScope(organization.id), workspace_folder_id=folder.id
        )
    session.rollback()
    failed = IngestionService(session).fail(
        job_id=failed_job.id,
        error_code="embedding_failed",
        expected_run_token=failed_token,
    )

    restored = session.scalar(select(DocumentChunk))
    assert failed is not None and failed.error_code == "embedding_failed"
    assert folder.status == "partial_failure"
    assert restored is not None and (restored.id, restored.text, restored.embedding) == (old_chunk_id, old_text, old_vector)
    assert "replacement scope" not in restored.text


def test_embedding_rate_limit_retries_only_current_batch_and_records_usage_once(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    organization, user, folder = workspace(session)
    discovered = [document("a" * ((16 * 1200) + 1))]
    _, _, _ = stage_sync(session, organization, user, folder, discovered)

    class RateLimitedOnceProvider(FakeEmbeddingProvider):
        def embed(self, *, texts: list[str]) -> list[list[float]]:
            self.calls.append(texts)
            if len(self.calls) == 1:
                raise AIProviderRateLimited(0.25)
            return [[float(index + 1), 1.0] for index, _ in enumerate(texts)]

    provider = RateLimitedOnceProvider()
    sleeps: list[float] = []
    monkeypatch.setattr("app.knowledge.questions.time.sleep", sleeps.append)

    embedded = EmbeddingService(session, provider).embed_workspace(
        scope=OrganizationScope(organization.id), workspace_folder_id=folder.id
    )

    chunks = list(session.scalars(select(DocumentChunk).order_by(DocumentChunk.position)))
    usage = session.scalar(select(UsageRecord).where(UsageRecord.metric == "embedding_tokens"))
    assert embedded == 17
    assert [len(batch) for batch in provider.calls] == [16, 16, 1]
    assert provider.calls[0] == provider.calls[1]
    assert sleeps == [0.25]
    assert all(chunk.embedding is not None for chunk in chunks)
    assert usage is not None and usage.quantity == sum((len(chunk.text) + 3) // 4 for chunk in chunks)
