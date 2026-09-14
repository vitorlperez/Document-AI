import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
OFFLINE_DATABASE_URL = "postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db"


def test_authentication_migration_generates_hashed_session_and_invitation_schema() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=BACKEND_DIR,
        env=os.environ | {"DATABASE_URL": OFFLINE_DATABASE_URL},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    sql = result.stdout
    assert "ALTER TABLE memberships ADD COLUMN deactivated_at" in sql
    for table in ("auth_identities", "user_sessions", "membership_invitations"):
        assert f"CREATE TABLE {table}" in sql
    assert "secret_hash VARCHAR(64) NOT NULL" in sql
    assert "token_hash VARCHAR(64) NOT NULL" in sql
    assert "uq_auth_identities_provider_subject" in sql
    assert "uq_membership_invitations_pending_org_email" in sql
    assert "WHERE accepted_at IS NULL AND revoked_at IS NULL" in sql
    assert "ALTER TABLE users DROP CONSTRAINT users_email_key" in sql
    assert "CREATE INDEX ix_users_email ON users (email)" in sql
    for table in ("data_sources", "oauth_connection_states", "workspace_folders"):
        assert f"CREATE TABLE {table}" in sql
    assert "encrypted_credentials TEXT NOT NULL" in sql
    assert "uq_workspace_folders_source_external" in sql
