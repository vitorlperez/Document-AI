"""The repair is tenant safe, repeatable and preserves genuine extraction errors."""
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.ingestion.models import ProcessingJob
from app.ingestion.service import IngestionService
from app.knowledge.models import Document
from app.library.models import ManualSyncRun
from app.library.service import LibraryService
from app.workspaces.models import WorkspaceFolder
from tests.integration.test_pgvector_search import engine, run_alembic  # noqa: F401
from tests.sync_helpers import T0, seed, space

pytestmark = pytest.mark.postgres
spec = importlib.util.spec_from_file_location('empty_migration', Path(__file__).resolve().parents[2] /
                                            'alembic/versions/20261001_0027_empty_documents_skipped.py')
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def test_repair_is_idempotent_and_preserves_real_failures(engine, test_database_url):  # noqa: F811
    with Session(engine) as session:
        org, user, source = seed(session)
        scope = OrganizationScope(org.id)
        folder_ids = []
        for number, real in enumerate([False, True]):
            folder = space(session, org, source, f'Space {number}', created_at=T0)
            folder_ids.append(folder.id)
            job = IngestionService(session).enqueue(scope=scope, user_id=user.id, workspace_folder_id=folder.id)
            job.status = 'partial_failure'
            folder.status = 'partial_failure'
            codes = ['empty_document'] + (['empty_extracted_text'] if real else [])
            for index, code in enumerate(codes):
                session.add(Document(organization_id=org.id, workspace_folder_id=folder.id,
                                     external_file_id=str(index), name=f'File {index}', mime_type='application/pdf' if index else 'text/plain',
                                     source_url='', content_hash='', index_status='failed', error_code=code))
            run = session.scalar(select(ManualSyncRun).where(ManualSyncRun.scope_external_id == str(job.id)))
            run.status = 'partial_failure'
            run.progress = {str(job.id): {'workspace_folder_id': str(folder.id), 'status': 'partial_failure',
                                          'error_code': None, 'failed': len(codes), 'processed': len(codes), 'total': len(codes),
                                          'outcomes': [{'external_id': str(i), 'name': f'File {i}', 'processed': True,
                                                        'error_code': code} for i, code in enumerate(codes)]}}
        session.commit()
        run_alembic('downgrade', '20260930_0026', database_url=test_database_url)
        run_alembic('upgrade', 'head', database_url=test_database_url)
        session.expire_all()
        first = list(session.execute(select(ManualSyncRun.progress)).scalars())
        migration.repair(session.connection())
        session.commit()
        session.expire_all()
        assert list(session.execute(select(ManualSyncRun.progress)).scalars()) == first
        assert [session.get(WorkspaceFolder, f).status for f in folder_ids] == ['ready', 'partial_failure']
        docs = list(session.scalars(select(Document).order_by(Document.error_code)))
        assert sum(d.index_status == 'skipped' for d in docs) == 2
        assert [d.error_code for d in docs if d.index_status == 'failed'] == ['empty_extracted_text']
        failures = IngestionService(session).nonindexed_documents(scope=scope, user_id=user.id, workspace_folder_id=folder_ids[0])
        assert failures == []
        status = LibraryService(session).sync_status(scope=scope, user_id=user.id)[0]
        assert (status['failed'], status['skipped']) == (1, 2)



def test_pre_snapshot_jobs_are_repaired_without_hiding_provider_failure_or_active_work(engine):  # noqa: F811
    with Session(engine) as session:
        org, user, source = seed(session)
        folder_ids, job_ids = [], []
        for number, (status, error) in enumerate([('partial_failure', None), ('failed', 'provider_error'), ('syncing', None)]):
            folder = space(session, org, source, f'Legacy {number}', created_at=T0)
            job = IngestionService(session).enqueue(scope=OrganizationScope(org.id), user_id=user.id, workspace_folder_id=folder.id)
            job.status, job.error_code, folder.status = status, error, status
            session.delete(session.scalar(select(ManualSyncRun).where(ManualSyncRun.scope_external_id == str(job.id))))
            session.add(Document(organization_id=org.id, workspace_folder_id=folder.id, external_file_id='blank',
                                 name='Blank', mime_type='text/plain', source_url='', content_hash='',
                                 index_status='failed', error_code='empty_document'))
            folder_ids.append(folder.id)
            job_ids.append(job.id)
        session.commit()
        migration.repair(session.connection())
        session.commit()
        session.expire_all()
        assert [session.get(ProcessingJob, j).status.value for j in job_ids] == ['ready', 'failed', 'syncing']
        assert [session.get(WorkspaceFolder, f).status for f in folder_ids] == ['ready', 'failed', 'syncing']
        assert session.get(ProcessingJob, job_ids[1]).error_code == 'provider_error'
