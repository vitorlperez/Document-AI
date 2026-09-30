import os

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "postgres: requires a disposable PostgreSQL TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Return the explicitly configured disposable PostgreSQL database URL.

    Integration tests never infer this from application configuration so a local
    developer database cannot accidentally be modified by the test suite.
    """
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PostgreSQL integration tests require TEST_DATABASE_URL")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.fail("TEST_DATABASE_URL must point to PostgreSQL")
    return database_url


@pytest.fixture(autouse=True)
def no_manual_sync_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests trigger several manual syncs back to back; the cooldown has its own test."""
    from app.library import manual_sync

    monkeypatch.setattr(manual_sync, "SYNC_COOLDOWN_SECONDS", 0)
