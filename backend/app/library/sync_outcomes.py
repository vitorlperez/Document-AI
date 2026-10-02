"""Compatibility for proven empty native documents in historical sync snapshots.

Do not include empty_extracted_text: it also means a scanned PDF needs OCR.
Counters may exceed the bounded sample, so subtract only confirmed old failures.
"""

EMPTY_CODES = frozenset({'empty_document', 'empty_content'})


def normalize_task(task: dict) -> dict:
    result = dict(task)
    original = task.get('outcomes', [])
    converted = sum(item.get('error_code') in EMPTY_CODES for item in original)
    result['outcomes'] = [
        {**item, 'error_code': None, 'status': 'skipped', 'reason': 'empty_content'}
        if item.get('error_code') in EMPTY_CODES else dict(item)
        for item in original
    ]
    result['failed'] = max(0, task.get('failed', sum(bool(i.get('error_code')) for i in original)) - converted)
    result['skipped'] = task.get('skipped', sum(
        i.get('status') == 'skipped' and not i.get('error_code') for i in original
    )) + converted
    empty_job_error = result.get('error_code') in EMPTY_CODES
    if empty_job_error:
        result['error_code'] = None
    if ((converted or empty_job_error) and result.get('status') in {'partial_failure', 'failed'}
            and not result['failed'] and not result.get('error_code')):
        result['status'] = 'ready'
    return result


def aggregate_status(tasks: list[dict], fallback: str) -> str:
    statuses = [task.get('status') for task in tasks]
    if not statuses:
        return fallback
    if 'syncing' in statuses:
        return 'syncing'
    if 'queued' in statuses:
        return 'queued'
    if all(status == 'failed' for status in statuses):
        return 'failed'
    return 'partial_failure' if any(s in {'failed', 'partial_failure'} for s in statuses) else 'ready'
