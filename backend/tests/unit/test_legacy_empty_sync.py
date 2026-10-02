from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.library.manual_sync import serialize_run
from app.library.models import ManualSyncRun


@pytest.mark.parametrize('scope', ['sync', 'workspace'])
@pytest.mark.parametrize('real_error', [None, 'empty_extracted_text', 'file_too_large'])
def test_legacy_empty_outcomes_are_neutral_without_mutating_snapshot(scope, real_error):
    outcomes = [{'external_id': 'blank', 'name': 'Blank', 'processed': True, 'error_code': 'empty_document'}]
    if real_error:
        outcomes.append({'external_id': 'real', 'name': 'Real', 'processed': True, 'error_code': real_error})
    task = {'workspace_folder_id': str(uuid4()), 'status': 'partial_failure', 'error_code': None,
            'total': len(outcomes), 'processed': len(outcomes), 'failed': len(outcomes), 'outcomes': outcomes}
    run = ManualSyncRun(id=uuid4(), organization_id=uuid4(), source_id=uuid4(), scope_kind=scope,
                        scope_external_id=str(uuid4()), scope_name='Space', triggered_by='QA',
                        status='partial_failure', created_at=datetime.now(UTC), progress={'job': task})
    result = serialize_run(run)
    assert result['failed'] == bool(real_error)
    assert result['skipped'] == 1
    assert result['status'] == ('partial_failure' if real_error else 'ready')
    assert result['tasks'][0]['status'] == result['status']
    assert result['skipped_items'] == [{'external_id': 'blank', 'name': 'Blank', 'reason': 'empty_content'}]
    assert [x['error_code'] for x in result['failures']] == ([real_error] if real_error else [])
    assert task['failed'] == len(outcomes) and outcomes[0]['error_code'] == 'empty_document'


def test_bounded_samples_preserve_unknown_failures_and_job_errors():
    from app.library.sync_outcomes import normalize_task

    task = {'status': 'partial_failure', 'error_code': None, 'failed': 200, 'skipped': 3,
            'outcomes': [{'external_id': 'blank', 'error_code': 'empty_document'}]}
    result = normalize_task(task)
    assert (result['failed'], result['skipped'], result['status']) == (199, 4, 'partial_failure')
    assert normalize_task(result) == result
    task.update(failed=1, error_code='provider_error', status='failed')
    result = normalize_task(task)
    assert (result['failed'], result['status'], result['error_code']) == (0, 'failed', 'provider_error')


def test_empty_job_error_does_not_hide_active_work_or_unknown_document_errors():
    from app.library.sync_outcomes import normalize_task

    for status in ['queued', 'syncing']:
        task = {'status': status, 'error_code': 'empty_document', 'outcomes': []}
        assert normalize_task(task)['status'] == status
    for code in ['no_text', 'no_extractable_text', 'empty', 'empty_extracted_text', 'text_extraction_failed']:
        task = {'status': 'partial_failure', 'error_code': None, 'outcomes': [{'error_code': code}]}
        result = normalize_task(task)
        assert (result['failed'], result['skipped'], result['status']) == (1, 0, 'partial_failure')
