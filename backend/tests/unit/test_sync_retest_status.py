"""N-06: file job scope must not replace folder-wide status or counters."""
from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.ingestion.models import ProcessingJob, ProcessingJobStatus
from app.knowledge.models import Document, DocumentChunk
from app.knowledge.questions import EMBEDDING_MODEL
from app.library.models import ManualSyncRun
from app.library.service import LibraryService
from tests.sync_helpers import T0, seed, space

CASES = [
    ('file', 'failed', 'ready', False, True, 'partial_failure', 'file_error'),
    ('files', 'failed', 'ready', False, True, 'partial_failure', 'file_error'),
    ('file', 'partial_failure', 'ready', False, True, 'partial_failure', 'file_error'),
    ('file', 'ready', 'ready', False, True, 'ready', None),
    ('file', 'queued', 'ready', False, True, 'ready', None),
    ('file', 'failed', 'ready', True, True, 'ready', None),
    ('file', 'failed', 'failed', False, True, 'partial_failure', 'folder_error'),
    ('file', 'failed', 'queued', True, True, 'queued', None),
    ('file', 'failed', None, False, True, 'partial_failure', 'file_error'),
    ('file', 'failed', None, False, False, 'failed', 'file_error'),
    # QF-09: newest folder job failed but the folder is still queryable -> partial, keeping error_code.
    ('workspace', 'failed', 'failed', False, False, 'failed', 'file_error'),
    ('workspace', 'failed', 'ready', False, True, 'partial_failure', 'file_error'),
    ('folder', 'failed', 'ready', False, True, 'partial_failure', 'file_error'),
    ('source', 'failed', 'ready', False, True, 'partial_failure', 'file_error'),
]
PARAMS = 'kind,file_status,folder_status,newer_folder,queryable,state,error'


def assert_file_scope_status(session, kind, file_status, folder_status, newer_folder, queryable, state, error):
    org, user, source = seed(session)
    folder = space(session, org, source, 'Tool status', created_at=T0)
    folder.status = 'partial_failure' if queryable else 'failed'
    if queryable:
        document = Document(organization_id=org.id, workspace_folder_id=folder.id,
            external_file_id='file', name='File', mime_type='text/plain', source_url='',
            content_hash='hash', processing_version='v1', index_status='indexed')
        session.add(document)
        session.flush()
        session.add(DocumentChunk(organization_id=org.id, workspace_folder_id=folder.id,
            document_id=document.id, position=0, text='Available', search_text='Available',
            embedding=[1.0, 0.0], embedding_model=EMBEDDING_MODEL))
    if folder_status:
        full = ProcessingJob(organization_id=org.id, workspace_folder_id=folder.id,
            status=ProcessingJobStatus(folder_status), idempotency_key='full',
            created_at=T0 + timedelta(seconds=2 if newer_folder else 0),
            error_code='folder_error' if folder_status == 'failed' else None)
        session.add(full)
        session.flush()
    run = ManualSyncRun(organization_id=org.id, source_id=source.id, scope_kind=kind,
        scope_external_id='file', scope_name='File', triggered_by_user_id=user.id,
        triggered_by=user.email, progress={})
    session.add(run)
    session.flush()
    retry = ProcessingJob(organization_id=org.id, workspace_folder_id=folder.id,
        status=ProcessingJobStatus(file_status), idempotency_key='retry', manual_run_id=run.id,
        created_at=T0 + timedelta(seconds=1),
        error_code='file_error' if file_status in {'failed', 'partial_failure'} else None)
    session.add(retry)
    session.flush()
    result = LibraryService(session).sync_status(scope=OrganizationScope(org.id), user_id=user.id)[0]
    assert (result['state'], result['error_code'], result['queryable']) == (state, error, queryable)
    return result


@pytest.mark.parametrize(PARAMS, CASES)
def test_n06_tool_state_tracks_folder_sync_not_file_retry(kind, file_status, folder_status, newer_folder, queryable, state, error):
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            assert_file_scope_status(session, kind, file_status, folder_status, newer_folder, queryable, state, error)
    finally:
        engine.dispose()


@pytest.mark.parametrize('count,kind', [(0, 'sync'), (1, 'file'), (2, 'files')])
def test_n06_document_batch_records_scope_without_forcing_full_discovery(count, kind):
    from sqlalchemy import select

    from app.ingestion.service import IngestionService
    from app.library.manual_sync import run_mode
    from tests.sync_helpers import doc

    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            org, user, source = seed(session)
            folder = space(session, org, source, 'Batch', created_at=T0)
            service = IngestionService(session)
            first = service.enqueue(scope=OrganizationScope(org.id), user_id=user.id, workspace_folder_id=folder.id)
            service.reconcile(job_id=first.id, documents=[doc(str(i)) for i in range(3)])
            documents = list(session.scalars(select(Document).order_by(Document.external_file_id)))
            retry = service.request_documents_reprocess(scope=OrganizationScope(org.id), user_id=user.id,
                workspace_folder_id=folder.id, document_ids=[document.id for document in documents[:count]])
            run = session.scalar(select(ManualSyncRun).where(
                ManualSyncRun.id == retry.manual_run_id if retry.manual_run_id else
                ManualSyncRun.scope_external_id == str(retry.id)))
            assert run.scope_kind == kind
            if count:
                assert run_mode(session, retry) == 'incremental'
            assert all(document.content_hash == '' for document in documents[:count])
            assert all(document.content_hash != '' for document in documents[count:])
    finally:
        engine.dispose()
