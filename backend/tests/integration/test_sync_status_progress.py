"""Exercise the production DISTINCT ON and JSON counter projection on Postgres."""
from uuid import UUID

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.ingestion.models import ProcessingJob, ProcessingJobStatus
from app.ingestion.service import IngestionService
from app.library.manual_sync import record_sync
from app.library.models import ManualSyncRun
from app.library.service import LibraryService
from tests.integration import test_pgvector_search
from tests.sync_helpers import T0, seed, space

pytestmark = pytest.mark.postgres
engine = test_pgvector_search.engine


def test_poll_uses_distinct_on_and_scalar_counters_with_deterministic_ties(engine):
    with Session(engine) as session:
        org, user, source = seed(session)
        folder = space(session, org, source, 'Poll', created_at=T0)
        service = IngestionService(session)
        job = service.enqueue(scope=OrganizationScope(org.id), user_id=user.id,
                              workspace_folder_id=folder.id)
        job.status = ProcessingJobStatus.READY
        session.flush()
        newest = ProcessingJob(id=UUID(int=(1 << 128) - 1), organization_id=org.id,
            workspace_folder_id=folder.id, status=ProcessingJobStatus.READY,
            idempotency_key='tie', created_at=job.created_at)
        session.add(newest)
        session.flush()
        record_sync(session, newest, folder, None)
        run = session.scalar(select(ManualSyncRun).where(ManualSyncRun.scope_external_id == str(newest.id)))
        run.progress = {str(newest.id): {'total': 5000, 'processed': 4999, 'failed': 1,
            'stage': 'done', 'outcomes': [{'external_id': str(i), 'error_code': None} for i in range(5000)]}}
        session.commit()
        statements = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(engine, 'before_cursor_execute', capture)
        try:
            result = LibraryService(session).sync_status(scope=OrganizationScope(org.id), user_id=user.id)[0]
        finally:
            event.remove(engine, 'before_cursor_execute', capture)
        assert (result['processed'], result['total'], result['failed']) == (4999, 5000, 1)
        assert any('DISTINCT ON (processing_jobs.workspace_folder_id)' in sql for sql in statements)
        progress_queries = [sql for sql in statements if 'manual_sync_runs.progress' in sql]
        assert len(progress_queries) == 1
        assert 'JOIN processing_jobs' in progress_queries[0]
        assert 'outcomes' not in progress_queries[0]
        assert 'AS processed' in progress_queries[0]


def test_embedding_stage_is_visible_without_committing_pending_documents(engine, monkeypatch):
    from types import SimpleNamespace

    from sqlalchemy import func
    from sqlalchemy.orm import sessionmaker

    from app.ingestion import tasks
    from app.knowledge.models import Document
    from app.knowledge.questions import EmbeddingService
    from tests.sync_helpers import doc

    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        org, user, source = seed(session)
        folder = space(session, org, source, 'Atomic stages', created_at=T0)
        job = IngestionService(session).enqueue(scope=OrganizationScope(org.id), user_id=user.id,
                                              workspace_folder_id=folder.id)
        job_id, org_id, user_id = job.id, org.id, user.id
    documents = [doc(str(i), text=f'Content {i}') for i in range(26)]
    provider = SimpleNamespace(discover=lambda **kwargs: documents, folders=lambda **kwargs: [])
    monkeypatch.setattr(tasks, 'get_settings', lambda: SimpleNamespace(openai_api_key=None, active_document_limit=500))
    monkeypatch.setattr(tasks, 'build_engine', lambda _: engine)
    monkeypatch.setattr(tasks, 'build_session_factory', lambda _: factory)
    monkeypatch.setattr(tasks, 'IntegrationRegistry', lambda _: SimpleNamespace(get=lambda *a, **kw: provider))
    monkeypatch.setattr(tasks, 'OpenAIQuestionProvider', lambda _: SimpleNamespace(
        embed=lambda *, texts: [[1.0] * 1536 for _ in texts]))
    original = EmbeddingService.embed_workspace
    observations = []

    def embed(self, **kwargs):
        with factory() as observer:
            run = observer.scalar(select(ManualSyncRun))
            progress = run.progress[str(job_id)]
            status = LibraryService(observer).sync_status(scope=OrganizationScope(org_id), user_id=user_id)[0]
            assert progress['stage'] == status['stage'] == 'embedding'
            observations.append(observer.scalar(select(func.count(Document.id))))
        return original(self, **kwargs)

    monkeypatch.setattr(EmbeddingService, 'embed_workspace', embed)
    assert tasks.reconcile_workspace_folder.apply(args=[str(job_id)], throw=True).successful()
    # Stage publication did not expose the current unembedded batch.
    assert observations == [0, 25, 26]
    with factory() as session:
        assert session.get(ProcessingJob, job_id).status == ProcessingJobStatus.READY
