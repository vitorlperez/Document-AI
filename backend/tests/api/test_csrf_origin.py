"""Cookie authenticated mutations must come from the configured UI origin."""

import importlib

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.models import Base


def _use_empty_database(app) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    app.state.session_factory = sessionmaker(bind=engine, expire_on_commit=False)


def test_cookie_mutation_origin_gate(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db")
    app = importlib.import_module("app.main").create_app(
        Settings(
            database_url="postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db",
            public_app_url="https://app.example.test",
            environment="production",
            auth_proxy_secret="test-only-proxy-secret-at-least-32-chars",
            auth_trusted_proxy_cidrs="127.0.0.1/32",
        )
    )
    _use_empty_database(app)
    with TestClient(app) as client:
        client.cookies.set("document_intelligence_session", "opaque-session")
        url = "/auth/logout"
        assert client.post(url, headers={"Origin": "https://evil.example.test"}).status_code == 403
        assert client.post(url).status_code == 403
        assert client.post(url, headers={"Origin": "https://app.example.test"}).status_code == 200


def test_cross_site_fetch_metadata_blocks_even_with_allowed_origin(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db")
    app = importlib.import_module("app.main").create_app(
        Settings(
            database_url="postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db",
            public_app_url="https://app.example.test",
            environment="production",
            auth_proxy_secret="test-only-proxy-secret-at-least-32-chars",
            auth_trusted_proxy_cidrs="127.0.0.1/32",
        )
    )
    _use_empty_database(app)
    with TestClient(app) as client:
        client.cookies.set("document_intelligence_session", "opaque-session")
        assert client.post(
            "/auth/logout",
            headers={"Origin": "https://app.example.test", "Sec-Fetch-Site": "cross-site"},
        ).status_code == 403


def test_sign_up_accepts_only_the_canonical_www_origin_not_the_apex(monkeypatch) -> None:
    """Prod incident: /login on the apex posted Origin=apex and /auth/register answered 403 'origin not allowed'.

    The canonical origin stays a single host (PUBLIC_APP_URL); the frontend redirects apex -> www instead.
    An empty body proves the origin gate passed (422) without ever reaching the e-mail provider.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db")
    app = importlib.import_module("app.main").create_app(
        Settings(
            database_url="postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db",
            public_app_url="https://www.example.test",
            environment="production",
            auth_proxy_secret="test-only-proxy-secret-at-least-32-chars",
            auth_trusted_proxy_cidrs="127.0.0.1/32",
        )
    )
    _use_empty_database(app)
    with TestClient(app) as client:
        apex = client.post("/auth/register", json={}, headers={"Origin": "https://example.test"})
        assert (apex.status_code, apex.json()) == (403, {"detail": "origin not allowed"})
        assert client.post("/auth/register", json={}, headers={"Origin": "https://www.example.test"}).status_code == 422
