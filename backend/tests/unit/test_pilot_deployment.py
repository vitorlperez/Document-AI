import importlib

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings


def _options_request(monkeypatch: pytest.MonkeyPatch, origin: str):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")
    main = importlib.import_module("app.main")
    app = main.create_app(
        Settings(
            database_url="postgresql+psycopg://test:test@localhost/test",
            environment="production",
            public_app_url="https://app.example.com",
        )
    )
    with TestClient(app) as client:
        return client.options(
            "/health/live",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )


def test_pilot_api_allows_only_configured_browser_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _options_request(monkeypatch, "https://app.example.com")

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.example.com"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_pilot_api_rejects_other_browser_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _options_request(monkeypatch, "https://untrusted.example.com")

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
