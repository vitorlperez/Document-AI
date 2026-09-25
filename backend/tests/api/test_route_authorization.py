"""The API must reject unauthenticated requests before reaching private handlers."""

import importlib

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.models import Base


def test_all_private_routes_require_a_session(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db")
    app = importlib.import_module("app.main").create_app(
        Settings(
            database_url="postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db",
            public_app_url="http://app.example.test",
            environment="development",
        )
    )
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    app.state.session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/me").status_code == 401
        assert client.get("/data-sources", params={"organization_id": "00000000-0000-0000-0000-000000000001"}).status_code == 401
        assert client.get("/workspace-folders", params={"organization_id": "00000000-0000-0000-0000-000000000001"}).status_code == 401
        assert client.get("/platform/companies").status_code == 401
    engine.dispose()
