"""N-03/N-06: coverage reflects content; file retries preserve tool availability."""
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select

from app.core.scoping import OrganizationScope
from app.ingestion.models import ProcessingJob, ProcessingJobStatus
from app.ingestion.service import IngestionService
from app.knowledge.models import Document, DocumentChunk
from app.knowledge.questions import EMBEDDING_MODEL
from app.library.manual_sync import update_progress
from app.library.models import ManualSyncRun
from app.workspaces.models import WorkspaceFolder
from tests.api.test_company_library_api import api, login, seed_library  # noqa: F401
from tests.api.test_multiscope_questions_api import ask, corpus  # noqa: F401
from tests.api.test_text_search_api import search_api  # noqa: F401


@pytest.mark.parametrize('scope', ['folder', 'organization', 'selection'])
def test_n03_queryable_folder_can_also_be_pending_with_explicit_partial(corpus, scope):  # noqa: F811
    client, factory, _, org_id, folders, _ = corpus
    with factory.begin() as session:
        session.get(WorkspaceFolder, folders['notion']).status = 'syncing'
    if scope == 'folder':
        response = client.post(
            f"/workspace-folders/{folders['notion']}/questions?organization_id={org_id}",
            json={'question': 'When does the campaign launch?'})
        total = 1
    else:
        params = {'scope': scope}
        if scope == 'selection':
            params.update(providers=['notion'], mentions=[])
        response = ask(client, org_id, **params)
        total = 2 if scope == 'organization' else 1
    assert response.status_code == 200
    assert response.json()['coverage'] == {
        'total_folders': total, 'eligible_folders': total, 'pending_folders': 1, 'partial': True,
    }
    assert response.json()['citations']


@pytest.mark.parametrize('scope', ['folder', 'organization', 'selection'])
def test_n03_ready_folder_without_content_is_not_eligible_or_still_syncing(corpus, scope):  # noqa: F811
    client, factory, _, org_id, folders, _ = corpus
    with factory.begin() as session:
        session.query(DocumentChunk).filter_by(workspace_folder_id=folders['notion']).delete()
    if scope == 'folder':
        response = client.post(
            f"/workspace-folders/{folders['notion']}/questions?organization_id={org_id}",
            json={'question': 'When does the campaign launch?'})
        total = 1
    else:
        params = {'scope': scope}
        if scope == 'selection':
            params.update(providers=['notion'], mentions=[])
        response = ask(client, org_id, **params)
        total = 2 if scope == 'organization' else 1
    assert response.status_code == 200
    assert response.json()['coverage'] == {
        'total_folders': total, 'eligible_folders': total - 1, 'pending_folders': 0, 'partial': True,
    }


def test_n06_real_file_reprocess_failure_does_not_replace_completed_sync(api):  # noqa: F811
    client, factory = api
    login(client)
    org_id = UUID(client.post('/organizations', json={'name': 'Acme'}).json()['id'])
    seed_library(factory, str(org_id))
    client.app.state.ingestion_dispatcher = type('Dispatcher', (), {'dispatch': lambda self, job_id: None})()
    with factory.begin() as session:
        folder = session.scalar(select(WorkspaceFolder))
        document = session.scalar(select(Document))
        session.add(DocumentChunk(organization_id=org_id, workspace_folder_id=folder.id,
            document_id=document.id, position=0, text='Approved content', search_text='Approved content',
            embedding=[1.0, 0.0], embedding_model=EMBEDDING_MODEL))
        complete = IngestionService(session).enqueue_system(scope=OrganizationScope(org_id), workspace_folder_id=folder.id)
        complete.status = ProcessingJobStatus.READY
        complete.created_at -= timedelta(minutes=1)
        update_progress(session, complete, stage='done', processed=50, total=50)
        folder_id, document_id = folder.id, document.id
    response = client.post(f'/workspace-folders/{folder_id}/documents/{document_id}/reprocess?organization_id={org_id}')
    assert response.status_code == 202
    with factory.begin() as session:
        job = session.get(ProcessingJob, UUID(response.json()['job_id']))
        run = session.get(ManualSyncRun, job.manual_run_id)
        assert run is not None and run.scope_kind == 'file'
        assert run.scope_external_id == 'brief'
        IngestionService(session).fail(job_id=job.id, error_code='workspace_scope_not_found')
    result = client.get(f'/library/sync-status?organization_id={org_id}')
    assert result.status_code == 200
    item = result.json()['items'][0]
    assert item['state'] == 'partial_failure'
    assert item['queryable'] is True and item['error_code'] == 'workspace_scope_not_found'
    assert (item['processed'], item['total']) == (50, 50)
