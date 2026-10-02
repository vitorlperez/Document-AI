"""Empty files are skipped (history only), never reported as sync failures."""
from types import SimpleNamespace

import pytest
from celery.exceptions import Retry
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.audit_usage.models import UsageRecord
from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.ingestion import tasks
from app.ingestion.blocks import ExtractedBlock
from app.ingestion.extraction import extract_blocks
from app.ingestion.models import ProcessingJob
from app.ingestion.service import DiscoveredDocument, DiscoveryResult, IngestionService
from app.knowledge.models import Document, DocumentChunk
from app.knowledge.questions import AIProviderUnavailable, EmbeddingService
from app.library.manual_sync import serialize_run
from app.library.models import ManualSyncRun
from app.library.service import LibraryService
from tests.sync_helpers import T0, doc, seed, space
from tests.unit.test_ingestion_embeddings import FakeEmbeddingProvider


def _worker(monkeypatch, tmp_path, documents):
    engine = create_engine(f"sqlite:///{tmp_path}/sync.db")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        org, user, source = seed(session)
        folder = space(session, org, source, "First access", created_at=T0)
        job = IngestionService(session).enqueue(scope=OrganizationScope(org.id), user_id=user.id,
                                              workspace_folder_id=folder.id)
        ids = SimpleNamespace(org=org.id, user=user.id, folder=folder.id, job=job.id)

    class Provider:
        def discover(self, **kwargs):
            return DiscoveryResult(documents=documents)

        def folders(self, **kwargs):
            return []

    monkeypatch.setattr(tasks, "get_settings", lambda: SimpleNamespace(openai_api_key=None, active_document_limit=500))
    monkeypatch.setattr(tasks, "build_engine", lambda _: engine)
    monkeypatch.setattr(tasks, "build_session_factory", lambda _: factory)
    monkeypatch.setattr(tasks, "IntegrationRegistry", lambda _: SimpleNamespace(get=lambda *a, **kw: Provider()))
    monkeypatch.setattr(tasks, "OpenAIQuestionProvider", lambda _: FakeEmbeddingProvider())
    return engine, factory, ids


def _history(session):
    return serialize_run(session.scalar(select(ManualSyncRun)))


def _status(session, ids):
    return LibraryService(session).sync_status(scope=OrganizationScope(ids.org), user_id=ids.user)[0]


def test_empty_files_are_skipped_and_the_job_is_ready(monkeypatch, tmp_path):
    documents = [doc("good", text="Approved scope"), doc("blank", text=""), doc("spaces", text="  \n ")]
    engine, factory, ids = _worker(monkeypatch, tmp_path, documents)
    assert tasks.reconcile_workspace_folder.apply(args=[str(ids.job)], throw=True).successful()
    with factory() as session:
        assert session.get(ProcessingJob, ids.job).status.value == "ready"
        rows = {row.external_file_id: row for row in session.scalars(select(Document))}
        assert (rows["blank"].index_status, rows["blank"].error_code) == ("skipped", "empty_content")
        assert rows["spaces"].index_status == "skipped"
        # No chunks (hence no embedding cost) for skipped files.
        assert set(session.scalars(select(DocumentChunk.document_id))) == {rows["good"].id}
        history = _history(session)
        assert (history["status"], history["total"], history["processed"]) == ("ready", 3, 3)
        assert (history["failed"], history["failures"], history["skipped"]) == (0, [], 2)
        assert sorted(history["skipped_items"], key=lambda item: item["name"]) == [
            {"external_id": "blank", "name": "blank.pdf", "reason": "empty_content"},
            {"external_id": "spaces", "name": "spaces.pdf", "reason": "empty_content"},
        ]
        status = _status(session, ids)
        assert (status["state"], status["processed"], status["total"], status["failed"], status["skipped"]) == (
            "ready", 3, 3, 0, 2)
    engine.dispose()


def test_all_empty_files_finish_ready_with_nothing_queryable(monkeypatch, tmp_path):
    engine, factory, ids = _worker(monkeypatch, tmp_path, [doc("a", text=""), doc("b", text="")])
    assert tasks.reconcile_workspace_folder.apply(args=[str(ids.job)], throw=True).successful()
    with factory() as session:
        assert session.get(ProcessingJob, ids.job).status.value == "ready"
        assert session.scalar(select(func.count(DocumentChunk.id))) == 0
        status = _status(session, ids)
        assert (status["state"], status["skipped"], status["failed"], status["queryable"]) == ("ready", 2, 0, False)
        context = LibraryService(session).question_contexts(scope=OrganizationScope(ids.org), user_id=ids.user)[0]
        assert context.status == "ready" and context.query_status == "no_indexed_content"
    engine.dispose()


def test_real_failures_still_fail_next_to_skipped_files(monkeypatch, tmp_path):
    broken = DiscoveredDocument("broken", "broken.pdf", "application/pdf", "", error_code="text_extraction_failed")
    engine, factory, ids = _worker(monkeypatch, tmp_path, [doc("good"), doc("blank", text=""), broken])
    assert tasks.reconcile_workspace_folder.apply(args=[str(ids.job)], throw=True).successful()
    with factory() as session:
        assert session.get(ProcessingJob, ids.job).status.value == "partial_failure"
        history = _history(session)
        assert (history["failed"], history["skipped"]) == (1, 1)
        assert [item["external_id"] for item in history["failures"]] == ["broken"]
        assert [item["external_id"] for item in history["skipped_items"]] == ["blank"]
        assert _status(session, ids)["skipped"] == 1
    engine.dispose()


def test_retry_after_a_transient_failure_keeps_skipped_files_idempotent(monkeypatch, tmp_path):
    documents = [doc("good"), doc("blank", text="")]
    engine, factory, ids = _worker(monkeypatch, tmp_path, documents)
    original = EmbeddingService.embed_workspace
    calls = 0

    def embed(self, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise AIProviderUnavailable("transient")
        return original(self, **kwargs)

    monkeypatch.setattr(EmbeddingService, "embed_workspace", embed)
    with pytest.raises(Retry):
        tasks.reconcile_workspace_folder.apply(args=[str(ids.job)], throw=True)
    assert tasks.reconcile_workspace_folder.apply(args=[str(ids.job)], throw=True).successful()
    with factory() as session:
        assert session.get(ProcessingJob, ids.job).status.value == "ready"
        assert session.scalar(select(func.count(Document.id))) == 2
        assert session.scalar(select(Document.index_status).where(Document.external_file_id == "blank")) == "skipped"
        history = _history(session)
        assert (history["skipped"], history["failed"], len(history["skipped_items"])) == (1, 0, 1)
    engine.dispose()


def test_skipping_charges_no_usage_and_drops_stale_chunks(monkeypatch, tmp_path):
    engine, factory, ids = _worker(monkeypatch, tmp_path, [doc("page", text="Old body")])
    assert tasks.reconcile_workspace_folder.apply(args=[str(ids.job)], throw=True).successful()
    with factory.begin() as session:
        assert session.scalar(select(func.count(DocumentChunk.id))) == 1
        usage = dict(session.execute(select(UsageRecord.metric, func.sum(UsageRecord.quantity))
                                     .group_by(UsageRecord.metric)).all())
        service = IngestionService(session)
        job = service.enqueue(scope=OrganizationScope(ids.org), user_id=ids.user, workspace_folder_id=ids.folder)
    with factory.begin() as session:
        IngestionService(session).reconcile(job_id=job.id, documents=[doc("page", text="")])
    with factory() as session:
        assert session.get(ProcessingJob, job.id).status.value == "ready"
        assert session.scalar(select(Document.index_status)) == "skipped"
        assert session.scalar(select(func.count(DocumentChunk.id))) == 0
        assert dict(session.execute(select(UsageRecord.metric, func.sum(UsageRecord.quantity))
                                    .group_by(UsageRecord.metric)).all()) == usage
    engine.dispose()


def test_scanned_pdf_without_ocr_stays_a_failure(monkeypatch, tmp_path):
    scanned = DiscoveredDocument("scan", "scan.pdf", "application/pdf", "", text="",
                                 blocks=(ExtractedBlock("", page_number=1),))
    blank_ocr = DiscoveredDocument("blank-scan", "blank.pdf", "application/pdf", "", text="",
                                   blocks=(ExtractedBlock("", page_number=1, ocr=True),))
    engine, factory, ids = _worker(monkeypatch, tmp_path, [doc("good"), scanned, blank_ocr])
    assert tasks.reconcile_workspace_folder.apply(args=[str(ids.job)], throw=True).successful()
    with factory() as session:
        rows = {row.external_file_id: row for row in session.scalars(select(Document))}
        assert (rows["scan"].index_status, rows["scan"].error_code) == ("failed", "empty_extracted_text")
        assert rows["blank-scan"].index_status == "skipped"
        assert session.get(ProcessingJob, ids.job).status.value == "partial_failure"
    engine.dispose()


@pytest.mark.parametrize("mime_type", [
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/markdown",
])
def test_zero_byte_file_extracts_as_empty_not_corrupt(mime_type):
    assert extract_blocks(mime_type, b"") == []
