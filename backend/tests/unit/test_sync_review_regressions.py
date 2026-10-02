"""Regression coverage for the progressive-sync backend review."""
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select

from app.audit_usage.service import UsageService
from app.core.scoping import OrganizationScope
from app.ingestion import tasks
from app.ingestion.blocks import ExtractedBlock
from app.ingestion.models import ProcessingJob, ProcessingJobStatus
from app.ingestion.service import DiscoveryResult, IngestionService
from app.knowledge.models import DocumentChunk
from app.knowledge.questions import EMBEDDING_MODEL, EmbeddingService
from app.library import manual_sync
from app.library.models import ManualSyncRun
from app.library.service import LibraryService
from tests.unit import test_progressive_sync

worker = test_progressive_sync.worker


def test_replayed_ocr_is_not_charged_twice(worker, monkeypatch):
    factory, ids, documents = worker
    scanned = replace(documents[0], blocks=(ExtractedBlock(documents[0].text, ocr=True),))
    charges = []
    original = UsageService.check_and_record

    def record(self, **kwargs):
        charges.append(kwargs['metric'])
        return original(self, **kwargs)

    monkeypatch.setattr(UsageService, 'check_and_record', record)
    with factory.begin() as session:
        service = IngestionService(session)
        job = service.claim(job_id=ids.job)
        service.apply_reconciliation(job_id=job.id, run_token=job.run_token,
                                     documents=[scanned], finalize=False, remove_missing=False)
    with factory.begin() as session:
        job = session.get(ProcessingJob, ids.job)
        IngestionService(session).apply_reconciliation(job_id=job.id, run_token=job.run_token,
                                                      documents=[scanned], finalize=False, remove_missing=False)
    assert charges.count('ocr_pages') == 1
    with factory.begin() as session:
        job = session.get(ProcessingJob, ids.job)
        IngestionService(session).apply_reconciliation(
            job_id=job.id, run_token=job.run_token, documents=[replace(scanned, processing_version='new')],
            finalize=False, remove_missing=False)
    assert charges.count('ocr_pages') == 2


@pytest.mark.parametrize('model', [None, 'legacy-model'])
def test_empty_incremental_sync_backfills_embeddings(worker, model, monkeypatch):
    factory, ids, documents = worker
    with factory.begin() as session:
        job = session.get(ProcessingJob, ids.job)
        IngestionService(session)._upsert_indexed(job, documents[0], indexed_at=job.created_at)
        chunk = session.scalar(select(DocumentChunk))
        chunk.embedding = None if model is None else [1.0, 1.0]
        chunk.embedding_model = model
    provider = SimpleNamespace(discover=lambda **kwargs: DiscoveryResult(documents=[], full_snapshot=False),
                               folders=lambda **kwargs: [])
    monkeypatch.setattr(tasks, 'IntegrationRegistry', lambda _: SimpleNamespace(get=lambda *a, **kw: provider))
    assert tasks.reconcile_workspace_folder.apply(args=[str(ids.job)], throw=True).successful()
    with factory() as session:
        chunk = session.scalar(select(DocumentChunk))
        assert chunk.embedding is not None and chunk.embedding_model == EMBEDDING_MODEL


def test_sync_history_omits_success_outcomes_but_keeps_counts(worker):
    factory, ids, _ = worker
    with factory.begin() as session:
        run = session.scalar(select(ManualSyncRun))
        run.progress = {str(ids.job): {'status': 'syncing', 'total': 1000, 'processed': 1000,
            'failed': 1, 'outcomes': [
                {'external_id': str(i), 'processed': True, 'error_code': 'bad' if i == 0 else None}
                for i in range(1000)]}}
        result = manual_sync.serialize_run(run)
        assert (result['total'], result['processed'], result['failed']) == (1000, 1000, 1)
        assert len(result['tasks'][0]['outcomes']) == len(result['failures']) == 1
        manual_sync.update_progress(session, session.get(ProcessingJob, ids.job), stage='embedding')
        assert len(run.progress[str(ids.job)]['outcomes']) == 1
        assert run.progress[str(ids.job)]['failed'] == 1


def test_discovery_is_throttled_and_persists_last_value(worker, monkeypatch):
    _factory, ids, _ = worker
    updates = []
    original = manual_sync.update_progress

    def record(session, job, **kwargs):
        if kwargs.get('stage') == 'discovering':
            updates.append(kwargs.get('processed'))
        return original(session, job, **kwargs)

    monkeypatch.setattr(manual_sync, 'update_progress', record)
    monkeypatch.setattr(tasks, 'monotonic', lambda: 1.0, raising=False)
    assert tasks.reconcile_workspace_folder.apply(args=[str(ids.job)], throw=True).successful()
    assert updates[-1] == 51
    assert len(updates) <= 5


def test_batch_commits_renew_the_owned_job_lease(worker, monkeypatch):
    factory, ids, _ = worker
    leases = []
    original = EmbeddingService.embed_workspace

    def embed(self, **kwargs):
        with factory() as observer:
            leases.append(observer.get(ProcessingJob, ids.job).started_at)
        return original(self, **kwargs)

    monkeypatch.setattr(EmbeddingService, 'embed_workspace', embed)
    assert tasks.reconcile_workspace_folder.apply(args=[str(ids.job)], throw=True).successful()
    assert leases[1] > leases[0]
    assert leases[2] > leases[1]


def test_poll_projects_only_counters_and_prefers_active_job(worker):
    factory, ids, _ = worker
    with factory.begin() as session:
        active = session.get(ProcessingJob, ids.job)
        session.add(ProcessingJob(organization_id=ids.org, workspace_folder_id=ids.folder,
            status=ProcessingJobStatus.READY, idempotency_key='history', created_at=active.created_at + timedelta(seconds=1)))
    statements = []
    engine = factory.kw['bind']

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, 'before_cursor_execute', capture)
    try:
        with factory() as session:
            result = LibraryService(session).sync_status(scope=OrganizationScope(ids.org), user_id=ids.user)
            assert result[0]['state'] == 'queued'
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    progress_queries = [sql for sql in statements if 'manual_sync_runs.progress' in sql]
    assert progress_queries and all('AS processed' in sql and 'AS total' in sql for sql in progress_queries)
    assert all('outcomes' not in sql for sql in progress_queries)
