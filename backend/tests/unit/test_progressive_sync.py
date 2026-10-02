"""Durability at the worker boundary, observed through independent sessions."""
from types import SimpleNamespace

import pytest
from celery.exceptions import Retry
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.audit_usage.service import UsageLimitExceeded
from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.ingestion import tasks
from app.ingestion.models import ProcessingJob
from app.ingestion.service import DiscoveryResult, IngestionService
from app.knowledge.models import Document, DocumentChunk
from app.knowledge.queryability import folder_is_queryable
from app.knowledge.questions import AIProviderUnavailable, EmbeddingService
from app.library.models import LibraryNode, ManualSyncRun
from app.library.service import LibraryService
from app.workspaces.models import WorkspaceFolder
from tests.sync_helpers import T0, doc, seed, space
from tests.unit.test_ingestion_embeddings import FakeEmbeddingProvider


@pytest.fixture()
def worker(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/sync.db")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        org, user, source = seed(session)
        folder = space(session, org, source, "First access", created_at=T0)
        job = IngestionService(session).enqueue(scope=OrganizationScope(org.id), user_id=user.id,
                                              workspace_folder_id=folder.id)
        ids = SimpleNamespace(org=org.id, user=user.id, source=source.id, folder=folder.id, job=job.id)
    documents = [doc(f"file-{i:03}", text=f"Approved document {i}") for i in range(51)]

    class Provider:
        def discover(self, **kwargs):
            with factory() as session:
                assert session.get(ProcessingJob, ids.job).status.value == "syncing"
            for count in range(1, len(documents) + 1):
                kwargs["progress_callback"](count, len(documents))
                if count in {1, len(documents)}:
                    with factory() as observer:
                        progress = observer.scalar(select(ManualSyncRun)).progress[str(ids.job)]
                        assert (progress["stage"], progress["processed"], progress["total"]) == (
                            "discovering", count, len(documents))
            return DiscoveryResult(documents=documents)

        def folders(self, **kwargs):
            return []

    monkeypatch.setattr(tasks, "get_settings", lambda: SimpleNamespace(openai_api_key=None, active_document_limit=500))
    monkeypatch.setattr(tasks, "build_engine", lambda _: engine)
    monkeypatch.setattr(tasks, "build_session_factory", lambda _: factory)
    monkeypatch.setattr(tasks, "IntegrationRegistry", lambda _: SimpleNamespace(get=lambda *a, **kw: Provider()))
    monkeypatch.setattr(tasks, "OpenAIQuestionProvider", lambda _: FakeEmbeddingProvider())
    yield factory, ids, documents
    engine.dispose()


def test_batches_are_queryable_before_the_last_commit_and_retry_is_idempotent(worker, monkeypatch):
    factory, ids, _documents = worker
    calls = 0
    original = EmbeddingService.embed_workspace
    observed_ids = []

    def embed(self, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            with factory() as observer:
                folder = observer.get(WorkspaceFolder, ids.folder)
                assert folder.status == "syncing"
                assert folder_is_queryable(folder, observer)
                observed_ids.extend(observer.scalars(select(DocumentChunk.id)))
                assert len(observed_ids) == 25
                library = LibraryService(observer)
                context = library.question_contexts(scope=OrganizationScope(ids.org), user_id=ids.user)[0]
                assert context.query_status == "ready" and context.sync_in_progress
                status = library.sync_status(scope=OrganizationScope(ids.org), user_id=ids.user)[0]
                assert (status["state"], status["stage"], status["processed"], status["total"], status["queryable"]) == (
                    "syncing", "indexing", 25, 51, True)
                assert status["library_node_id"] == str(observer.scalar(select(LibraryNode.id).where(LibraryNode.kind == "source")))
            raise AIProviderUnavailable("transient failure")
        return original(self, **kwargs)

    monkeypatch.setattr(EmbeddingService, "embed_workspace", embed)
    with pytest.raises(Retry):
        tasks.reconcile_workspace_folder.apply(args=[str(ids.job)], throw=True)
    with factory() as session:
        assert session.get(ProcessingJob, ids.job).status.value == "queued"
        assert session.scalar(select(func.count(Document.id))) == 25
    # Replays the complete discovery: committed content hashes and vectors survive.
    assert tasks.reconcile_workspace_folder.apply(args=[str(ids.job)], throw=True).successful()
    with factory() as session:
        assert session.scalar(select(func.count(Document.id))) == 51
        assert session.scalar(select(func.count(DocumentChunk.id))) == 51
        assert set(observed_ids) <= set(session.scalars(select(DocumentChunk.id)))
        assert session.get(ProcessingJob, ids.job).status.value == "ready"
        progress = session.scalar(select(ManualSyncRun)).progress[str(ids.job)]
        assert (progress["processed"], progress["total"], progress["stage"]) == (51, 51, "done")
        assert len(set(session.scalars(select(LibraryNode.external_id)))) == 52


def test_quota_after_a_committed_batch_keeps_queryable_documents(worker, monkeypatch):
    factory, ids, _ = worker
    original = EmbeddingService.embed_workspace
    calls = 0

    def embed(self, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise UsageLimitExceeded("quota")
        return original(self, **kwargs)

    monkeypatch.setattr(EmbeddingService, "embed_workspace", embed)
    assert tasks.reconcile_workspace_folder.apply(args=[str(ids.job)], throw=True).successful()
    with factory() as session:
        status = LibraryService(session).sync_status(scope=OrganizationScope(ids.org), user_id=ids.user)[0]
        assert (status["state"], status["error_code"], status["processed"], status["total"], status["queryable"]) == (
            "partial_failure", "usage_limit_exceeded", 25, 51, True)  # QF-09: queryable => never "failed"
        assert session.get(WorkspaceFolder, ids.folder).status == "partial_failure"
        assert session.scalar(select(func.count(Document.id))) == 25


def test_resync_keeps_the_previous_snapshot_and_removes_missing_only_at_the_end(worker, monkeypatch):
    factory, ids, _ = worker
    with factory.begin() as session:
        folder = session.get(WorkspaceFolder, ids.folder)
        job = session.get(ProcessingJob, ids.job)
        # Seed a prior completed snapshot without creating a competing job.
        IngestionService(session)._upsert_indexed(job, doc("gone", text="Previous snapshot"), indexed_at=T0)
        EmbeddingService(session, FakeEmbeddingProvider()).embed_workspace(
            scope=OrganizationScope(ids.org), workspace_folder_id=folder.id)
        folder.status = "ready"
    original = EmbeddingService.embed_workspace
    calls = 0

    def embed(self, **kwargs):
        nonlocal calls
        calls += 1
        with factory() as observer:
            folder = observer.get(WorkspaceFolder, ids.folder)
            assert folder.status == "ready" and folder_is_queryable(folder, observer)
            old = observer.scalar(select(Document).where(Document.external_file_id == "gone"))
            assert old.index_status == "indexed"
            if calls == 2:
                assert observer.scalar(select(func.count(Document.id))) == 26
        return original(self, **kwargs)

    monkeypatch.setattr(EmbeddingService, "embed_workspace", embed)
    assert tasks.reconcile_workspace_folder.apply(args=[str(ids.job)], throw=True).successful()
    with factory() as session:
        old = session.scalar(select(Document).where(Document.external_file_id == "gone"))
        assert old.index_status == "removed"
        assert session.scalar(select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == old.id)) == 0
        assert session.scalar(select(func.count(Document.id)).where(Document.index_status == "indexed")) == 51
