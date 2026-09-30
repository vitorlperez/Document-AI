import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
OFFLINE_DATABASE_URL = "postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db"


def test_foundation_migration_generates_expected_postgresql_sql() -> None:
    environment = os.environ | {"DATABASE_URL": OFFLINE_DATABASE_URL}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    sql = result.stdout
    for table in ("organizations", "users", "memberships", "audit_logs"):
        assert f"CREATE TABLE {table}" in sql
    assert "CREATE TYPE membership_role" in sql
    assert "CREATE UNIQUE INDEX uq_memberships_active_org_user" in sql
    assert "WHERE is_active" in sql


def test_pgvector_expand_sql():
    result = subprocess.run(
        [sys.executable, '-m', 'alembic', 'upgrade', 'head', '--sql'],
        cwd=BACKEND_DIR, env=os.environ | {'DATABASE_URL': OFFLINE_DATABASE_URL},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert 'CREATE EXTENSION IF NOT EXISTS vector' in result.stdout
    assert 'ADD COLUMN embedding_vec vector(1536)' in result.stdout
    assert 'USING hnsw' not in result.stdout
    assert 'DROP COLUMN embedding' not in result.stdout


def test_access_migrations_generate_postgresql_sql():
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=BACKEND_DIR, env=os.environ | {"DATABASE_URL": OFFLINE_DATABASE_URL},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    for table in ("api_keys", "organization_access_settings", "api_audit_events"):
        assert f"CREATE TABLE {table}" in result.stdout
    assert "CREATE INDEX ix_api_audit_events_org_created" in result.stdout
