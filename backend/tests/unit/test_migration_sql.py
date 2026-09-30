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


def test_integration_migration_chain_preserves_main_revision():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["20260930_0025"]
    expected = [
        ("20260930_0019", "library_exclusions"),
        ("20260930_0020", "pgvector_expand"),
        ("20260930_0021", "sharepoint_tenant_binding"),
        ("20260930_0022", "extraction_cache"),
        ("20260930_0023", "api_access"),
        ("20260930_0024", "api_audit_events"),
        ("20260930_0025", "mcp_connections"),
    ]
    previous = "20260929_0018"
    for revision, slug in expected:
        migration = scripts.get_revision(revision)
        assert Path(migration.path).name == f"{revision}_{slug}.py"
        assert migration.down_revision == previous
        previous = revision


def test_mcp_migration_allows_rebinding_a_revoked_user_on_sqlite():
    import importlib.util

    import pytest
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import IntegrityError

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = BACKEND_DIR / "alembic/versions/20260930_0025_mcp_connections.py"
    spec = importlib.util.spec_from_file_location("mcp_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        insert = text("INSERT INTO mcp_connections (id, organization_id, user_id, revoked_at, created_at) "
                      "VALUES (:id, 'org', 'user', :revoked, CURRENT_TIMESTAMP)")
        connection.execute(insert, {"id": "first", "revoked": "2026-09-30"})
        connection.execute(insert, {"id": "second", "revoked": None})
        with pytest.raises(IntegrityError):
            connection.execute(insert, {"id": "third", "revoked": None})
