from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import health
from app.core.config import Settings


def make_health_client() -> TestClient:
    app = FastAPI()
    # The failing readiness branch is mocked before the route touches this value.
    app.state.engine = object()
    app.include_router(health.router)
    return TestClient(app)


def test_liveness_returns_ok_without_database_dependency() -> None:
    response = make_health_client().get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_failure_is_explainable_without_leaking_driver_details(monkeypatch) -> None:
    monkeypatch.setattr(health, "database_is_ready", lambda engine: False)

    response = make_health_client().get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    body = response.text.lower()
    assert "postgres" not in body
    assert "password" not in body
    assert "exception" not in body


def test_settings_require_database_url(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    try:
        Settings(_env_file=None)
    except ValidationError as error:
        assert "database_url" in str(error)
    else:
        raise AssertionError("Settings must reject a missing DATABASE_URL")


def test_railway_postgres_url_selects_installed_psycopg_driver() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql://user:password@postgres.railway.internal:5432/railway",
    )

    assert str(settings.database_url) == (
        "postgresql+psycopg://user:password@postgres.railway.internal:5432/railway"
    )
