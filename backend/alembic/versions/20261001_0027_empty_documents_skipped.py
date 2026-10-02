"""Reclassify proven empty native documents without deleting user content.

Frozen, idempotent repair; excludes scanned-PDF empty_extracted_text and unknown
aliases. Downgrade does not restore false failures. SQL works online and offline.
"""
import sqlalchemy as sa

from alembic import op

revision = '20261001_0027'
down_revision = '20260930_0026'
branch_labels = None
depends_on = None

REPAIR_SQL = r"""
DO $repair$
DECLARE
    empty_codes text[] := ARRAY['empty_document', 'empty_content'];
    affected uuid[] := ARRAY[]::uuid[];
    r record; t record; j record;
    next_progress jsonb; value jsonb; outcomes jsonb;
    converted integer; failures integer; ignored integer;
    old_failures integer; old_ignored integer;
    statuses text[]; run_status text; folder_id uuid;
BEGIN
    WITH changed AS (
        UPDATE documents SET index_status = 'skipped', error_code = 'empty_content'
        WHERE index_status = 'failed' AND error_code = ANY(empty_codes)
        RETURNING workspace_folder_id
    ) SELECT coalesce(array_agg(DISTINCT workspace_folder_id), ARRAY[]::uuid[])
      INTO affected FROM changed;

    FOR r IN SELECT * FROM manual_sync_runs FOR UPDATE LOOP
        next_progress := '{}'::jsonb;
        statuses := ARRAY[]::text[];
        FOR t IN SELECT * FROM jsonb_each(coalesce(r.progress::jsonb, '{}'::jsonb)) LOOP
            SELECT count(*) FILTER (WHERE o->>'error_code' = ANY(empty_codes)),
                   count(*) FILTER (WHERE coalesce(o->>'error_code', '') <> ''),
                   count(*) FILTER (WHERE o->>'status' = 'skipped' AND coalesce(o->>'error_code', '') = ''),
                   coalesce(jsonb_agg(CASE WHEN o->>'error_code' = ANY(empty_codes)
                       THEN o || jsonb_build_object('error_code', NULL, 'status', 'skipped', 'reason', 'empty_content')
                       ELSE o END), '[]'::jsonb)
            INTO converted, old_failures, old_ignored, outcomes
            FROM jsonb_array_elements(coalesce(t.value->'outcomes', '[]'::jsonb)) o;
            failures := greatest(0, coalesce((t.value->>'failed')::integer, old_failures) - converted);
            ignored := coalesce((t.value->>'skipped')::integer, old_ignored) + converted;
            value := t.value || jsonb_build_object('outcomes', outcomes, 'failed', failures, 'skipped', ignored);
            IF value->>'error_code' = ANY(empty_codes) THEN
                value := value || jsonb_build_object('error_code', NULL);
            END IF;
            IF (converted > 0 OR t.value->>'error_code' = ANY(empty_codes))
                AND value->>'status' IN ('partial_failure', 'failed')
                AND failures = 0 AND coalesce(value->>'error_code', '') = '' THEN
                value := value || '{"status":"ready"}'::jsonb;
            END IF;
            next_progress := next_progress || jsonb_build_object(t.key, value);
            statuses := array_append(statuses, value->>'status');
            IF t.value->>'status' IS DISTINCT FROM value->>'status' THEN
                -- Only the exact historical job and tenant, never every job in a space.
                FOR j IN UPDATE processing_jobs SET status = 'ready', error_code = NULL
                    WHERE id::text = t.key AND organization_id = r.organization_id
                      AND status IN ('failed', 'partial_failure')
                      AND (error_code IS NULL OR error_code = ANY(empty_codes))
                    RETURNING workspace_folder_id LOOP
                    affected := array_append(affected, j.workspace_folder_id);
                END LOOP;
            END IF;
        END LOOP;
        IF next_progress IS DISTINCT FROM coalesce(r.progress::jsonb, '{}'::jsonb) THEN
            run_status := CASE
                WHEN 'syncing' = ANY(statuses) THEN 'syncing'
                WHEN 'queued' = ANY(statuses) THEN 'queued'
                WHEN cardinality(statuses) > 0 AND 'failed' = ALL(statuses) THEN 'failed'
                WHEN statuses && ARRAY['failed', 'partial_failure'] THEN 'partial_failure'
                ELSE 'ready' END;
            UPDATE manual_sync_runs SET progress = next_progress, status = run_status WHERE id = r.id;
        END IF;
    END LOOP;
    -- Jobs without snapshots require an explicit, proven empty error.
    FOR j IN UPDATE processing_jobs SET status = 'ready', error_code = NULL
        WHERE status IN ('failed', 'partial_failure') AND error_code = ANY(empty_codes)
        RETURNING workspace_folder_id LOOP
        affected := array_append(affected, j.workspace_folder_id);
    END LOOP;
    FOREACH folder_id IN ARRAY affected LOOP
        IF NOT EXISTS (SELECT 1 FROM documents WHERE workspace_folder_id = folder_id AND index_status = 'failed')
           AND NOT EXISTS (SELECT 1 FROM processing_jobs WHERE workspace_folder_id = folder_id AND status IN ('queued', 'syncing')) THEN
            -- Pre-history partial jobs had no error code. Only the newest snapshot,
            -- with confirmed empty documents and no remaining document failures,
            -- can prove such a job finished cleanly. Older history is preserved.
            UPDATE processing_jobs p SET status = 'ready'
            WHERE p.id = (SELECT id FROM processing_jobs WHERE workspace_folder_id = folder_id
                          ORDER BY created_at DESC, id DESC LIMIT 1)
              AND p.status = 'partial_failure' AND p.error_code IS NULL
              AND NOT EXISTS (SELECT 1 FROM manual_sync_runs m WHERE m.organization_id = p.organization_id
                              AND (m.id = p.manual_run_id OR (m.scope_kind = 'sync' AND m.scope_external_id = p.id::text)));
            IF (SELECT status FROM processing_jobs WHERE workspace_folder_id = folder_id
                ORDER BY created_at DESC, id DESC LIMIT 1) = 'ready' THEN
                UPDATE workspace_folders SET status = 'ready'
                WHERE id = folder_id AND status IN ('partial_failure', 'failed');
            END IF;
        END IF;
    END LOOP;
END $repair$;
"""


def repair(bind):
    bind.execute(sa.text(REPAIR_SQL))


def upgrade():
    op.execute(sa.text(REPAIR_SQL))


def downgrade():
    pass
