"""Production must fail before serving requests with incomplete proxy trust."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings

DB = "postgresql+psycopg://test:test@localhost/test"
SECRET = "test-only-proxy-secret-at-least-32-chars"


@pytest.mark.parametrize("secret,cidrs,missing", [
    (None, "", "AUTH_PROXY_SECRET.*AUTH_TRUSTED_PROXY_CIDRS"),
    (None, "127.0.0.1/32", "AUTH_PROXY_SECRET"),
    (SECRET, "", "AUTH_TRUSTED_PROXY_CIDRS"),
    (SECRET, " , ", "AUTH_TRUSTED_PROXY_CIDRS"),
])
def test_production_requires_both_proxy_settings_at_startup(secret, cidrs, missing):
    with pytest.raises(ValidationError, match=missing) as error:
        Settings(_env_file=None, database_url=DB, environment="production",
                 auth_proxy_secret=secret, auth_trusted_proxy_cidrs=cidrs)
    assert SECRET not in str(error.value)


@pytest.mark.parametrize("secret,cidrs,invalid", [
    ("short", "127.0.0.1/32", "AUTH_PROXY_SECRET"),
    (" " * 32, "127.0.0.1/32", "AUTH_PROXY_SECRET"),
    (SECRET, "bad-network", "AUTH_TRUSTED_PROXY_CIDRS"),
    (SECRET, "0.0.0.0/0", "AUTH_TRUSTED_PROXY_CIDRS"),
    (SECRET, "::/0", "AUTH_TRUSTED_PROXY_CIDRS"),
    (SECRET, "127.0.0.1/32,bad-network", "AUTH_TRUSTED_PROXY_CIDRS"),
])
def test_production_rejects_invalid_proxy_configuration(secret, cidrs, invalid):
    with pytest.raises(ValidationError, match=invalid) as error:
        Settings(_env_file=None, database_url=DB, environment="production",
                 auth_proxy_secret=secret, auth_trusted_proxy_cidrs=cidrs)
    assert SECRET not in str(error.value)


def test_production_accepts_delimited_ipv4_and_ipv6_peers():
    Settings(_env_file=None, database_url=DB, environment="production",
             auth_proxy_secret=SECRET, auth_trusted_proxy_cidrs="127.0.0.1/32, ::1/128")


def test_development_can_run_without_proxy_configuration():
    Settings(_env_file=None, database_url=DB, environment="development",
             auth_proxy_secret=None, auth_trusted_proxy_cidrs="")


def test_production_api_import_fails_before_startup_without_proxy_trust(tmp_path):
    environment = os.environ | {
        "DATABASE_URL": DB, "ENVIRONMENT": "production",
        "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
    }
    for name in ("AUTH_PROXY_SECRET", "AUTH_TRUSTED_PROXY_CIDRS"):
        environment.pop(name, None)
    result = subprocess.run([sys.executable, "-c", "import app.main"],
                            cwd=tmp_path, env=environment, capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "Production requires valid AUTH_PROXY_SECRET and AUTH_TRUSTED_PROXY_CIDRS before startup" in result.stderr
    assert "input_value=" not in result.stderr
