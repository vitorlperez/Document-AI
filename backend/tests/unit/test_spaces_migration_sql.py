import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
URL = "postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db"


def test_offline_sql_creates_space_tables_and_skips_backfill() -> None:
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head", "--sql"], cwd=BACKEND_DIR,
                            env=os.environ | {"DATABASE_URL": URL}, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    for table in ("spaces", "space_members", "space_folder_grants"):
        assert f"CREATE TABLE {table}" in result.stdout
    assert "DROP COLUMN spaces_resolver_mode" in result.stdout
    assert "space_ids" in result.stdout
