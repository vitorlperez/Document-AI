"""Shared helpers for the library-scale spike.

Everything here talks to *separate* databases (spike_ls_*) created on the local dev
PostgreSQL server (docker compose service `postgres`). The application database
`document_intelligence` is never touched.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import UUID

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent.parent / "backend"
RESULTS = HERE / "results"
RESULTS.mkdir(exist_ok=True)

PG_HOST = os.environ.get("SPIKE_PG_HOST", "127.0.0.1")
PG_PORT = os.environ.get("SPIKE_PG_PORT", "5432")
PG_USER = os.environ.get("SPIKE_PG_USER", "document_intelligence")
PG_PASSWORD = os.environ.get("SPIKE_PG_PASSWORD", "document_intelligence")
TEMPLATE_DB = "spike_ls_tpl"  # alembic-migrated, empty
OWNER_EMAIL = "owner@spike.example.test"


def db_name(label: str) -> str:
    return f"spike_ls_{label}"


def dsn(database: str) -> str:
    """libpq URL for plain psycopg."""
    return f"postgresql://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{database}"


def sa_url(database: str) -> str:
    """SQLAlchemy URL (psycopg3 driver), same one the app uses."""
    return f"postgresql+psycopg://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{database}"


def ensure_backend_on_path() -> None:
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))


def migrate_template() -> None:
    """(Re)build the empty, migrated template database through the project's own alembic."""
    import psycopg

    with psycopg.connect(dsn("postgres"), autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {TEMPLATE_DB}")
        conn.execute(f"CREATE DATABASE {TEMPLATE_DB}")
    result = subprocess.run(
        [str(BACKEND / ".venv" / "bin" / "python"), "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND, env=os.environ | {"DATABASE_URL": sa_url(TEMPLATE_DB)},
        capture_output=True, text=True, check=False,
    )
    print(result.stdout[-400:], result.stderr[-400:])
    if result.returncode != 0:
        raise SystemExit(f"alembic failed: {result.returncode}")


def create_db_from_template(database: str) -> None:
    import psycopg

    with psycopg.connect(dsn("postgres"), autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {database} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {database} TEMPLATE {TEMPLATE_DB}")


class FakeAuthGateway:
    """Same stub the project's own API tests use (tests/integration/test_performance_paths_postgres.py)."""

    def authorization_url(self, *, state: str, screen_hint: str | None = None, max_age: int | None = None) -> str:
        return f"https://auth.example.test/login?state={state}"

    def exchange_code(self, *, code: str):
        from app.identity.auth import VerifiedIdentity

        return VerifiedIdentity(provider="workos", subject=code, email=f"{code}@spike.example.test")


class RandomEmbedProvider:
    """Question provider stub: deterministic embedding for a query, canned answer. No network."""

    def __init__(self, vector: list[float]):
        self.vector = vector
        self.embeds = 0

    def embed(self, *, texts):
        self.embeds += 1
        return [self.vector for _ in texts]

    def answer(self, *, question, evidence):
        from app.knowledge.questions import GeneratedAnswer

        return GeneratedAnswer("stub answer", list(range(1, min(len(evidence), 3) + 1)))


def make_client(database: str):
    """FastAPI TestClient bound to a spike database, the same way the project's postgres tests do it."""
    ensure_backend_on_path()
    os.environ["DATABASE_URL"] = sa_url(database)
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.config import Settings

    main = importlib.import_module("app.main")
    app = main.create_app(Settings(database_url=sa_url(database), public_app_url="http://app.example.test"))
    engine = create_engine(sa_url(database), pool_size=5)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app.state.session_factory = factory
    app.state.auth_gateway = FakeAuthGateway()
    client = TestClient(app)
    client.__enter__()
    return client, factory, engine


def login(client, code: str = "owner") -> None:
    started = client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    response = client.get(f"/auth/callback?code={code}&state={state}", follow_redirects=False)
    assert response.status_code == 302, response.text


def create_org(client, name: str) -> UUID:
    response = client.post("/organizations", json={"name": name})
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


def first_org(client) -> UUID:
    response = client.get("/organizations")
    assert response.status_code == 200, response.text
    return UUID(response.json()[0]["id"])


def load_meta(label: str) -> dict:
    return json.loads((RESULTS / f"meta_{label}.json").read_text())
