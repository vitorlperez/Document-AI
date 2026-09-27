"""PostgreSQL coverage for the batched library and workspace browse paths."""

import importlib
import os
from collections.abc import Generator
from statistics import median
from time import perf_counter
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.models import Base
from app.identity.auth import VerifiedIdentity
from app.identity.models import User
from app.integrations.models import DataSource
from app.knowledge.models import Document
from app.library.models import LibraryNode
from app.library.service import LibraryService
from app.workspaces.models import WorkspaceFolder, WorkspaceFolderSelection

pytestmark = pytest.mark.postgres


class FakeAuthGateway:
    def authorization_url(self, *, state: str, screen_hint: str | None = None, max_age: int | None = None) -> str:
        return f"https://auth.example.test/login?state={state}"

    def exchange_code(self, *, code: str) -> VerifiedIdentity:
        return VerifiedIdentity(provider="workos", subject=code, email=f"{code}@example.test")


@pytest.fixture()
def postgres_api(test_database_url: str, monkeypatch: pytest.MonkeyPatch) -> Generator[
    tuple[TestClient, sessionmaker[Session]], None, None
]:
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    main = importlib.import_module("app.main")
    app = main.create_app(Settings(database_url=test_database_url, public_app_url="http://app.example.test"))
    engine = create_engine(test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app.state.session_factory = factory
    app.state.auth_gateway = FakeAuthGateway()
    with TestClient(app) as client:
        yield client, factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def _login(client: TestClient) -> UUID:
    started = client.get("/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
    assert client.get(f"/auth/callback?code=owner&state={state}", follow_redirects=False).status_code == 302
    response = client.post("/organizations", json={"name": "Performance test"})
    assert response.status_code == 201
    return UUID(response.json()["id"])


def test_postgres_children_and_workspace_listing_use_one_batch_each(postgres_api) -> None:
    client, factory = postgres_api
    organization_id = _login(client)
    with factory.begin() as session:
        user = session.scalar(select(User).where(User.email == "owner@example.test"))
        source = DataSource(
            organization_id=organization_id, provider="google_drive", encrypted_credentials="test",
            status="connected", connected_by_user_id=user.id,
        )
        session.add(source)
        session.flush()
        root = LibraryNode(
            organization_id=organization_id, source_id=source.id, parent_id=None,
            external_id="__company_library_source_root__", kind="source", name="Drive",
        )
        session.add(root)
        session.flush()
        for folder_index in range(3):
            workspace = WorkspaceFolder(
                organization_id=organization_id, source_id=source.id,
                external_folder_id=f"scope-{folder_index}", name=f"Space {folder_index}",
                uniform_access_confirmed=True,
            )
            session.add(workspace)
            session.flush()
            session.add(WorkspaceFolderSelection(
                workspace_folder_id=workspace.id, kind="folder",
                external_folder_id=f"remote-{folder_index}",
            ))
            for file_index in range(12):
                external_id = f"file-{file_index}"
                session.add(Document(
                    organization_id=organization_id, workspace_folder_id=workspace.id,
                    external_file_id=external_id, name=f"File {file_index}",
                    mime_type="application/pdf", source_url="https://drive.example.test/file",
                    content_hash="hash", processing_version="v1", index_status="indexed",
                ))
                if folder_index == 0:
                    session.add(LibraryNode(
                        organization_id=organization_id, source_id=source.id,
                        parent_id=root.id, external_id=external_id, kind="file",
                        name=f"File {file_index}", mime_type="application/pdf",
                    ))

    statements: list[str] = []

    def collect(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().lower().startswith("select"):
            statements.append(statement.lower())

    engine = factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", collect)
    try:
        children = client.get(
            f"/library/nodes/{root.id}/children?organization_id={organization_id}"
        )
        child_queries = statements[:]
        statements.clear()
        folders = client.get(f"/workspace-folders?organization_id={organization_id}")
        folder_queries = statements[:]
    finally:
        event.remove(engine, "before_cursor_execute", collect)

    assert children.status_code == 200
    assert len(children.json()["items"]) == 12
    assert all(len(item["workspace_documents"]) == 3 for item in children.json()["items"])
    assert len([query for query in child_queries if "from documents" in query and "join workspace_folders" in query]) == 1
    assert folders.status_code == 200
    assert len(folders.json()) == 3
    assert [row["selection_folder_ids"] for row in folders.json()] == [
        ["remote-0"], ["remote-1"], ["remote-2"],
    ]
    assert len([query for query in folder_queries if "workspace_folder_selections" in query]) == 1

    if os.getenv("PERFORMANCE_TIMING") == "1":
        for path in (
            f"/library/nodes/{root.id}/children?organization_id={organization_id}",
            f"/workspace-folders?organization_id={organization_id}",
        ):
            for _ in range(3):
                assert client.get(path).status_code == 200
            samples = []
            for _ in range(30):
                start = perf_counter()
                assert client.get(path).status_code == 200
                samples.append((perf_counter() - start) * 1000)
            samples.sort()
            print(f"{path.split('?')[0]}: median={median(samples):.2f}ms p95={samples[28]:.2f}ms n=30")


def test_postgres_worker_folder_pruning_uses_bounded_reads(postgres_api) -> None:
    client, factory = postgres_api
    organization_id = _login(client)
    with factory.begin() as session:
        user = session.scalar(select(User).where(User.email == "owner@example.test"))
        source = DataSource(
            organization_id=organization_id, provider="google_drive", encrypted_credentials="test",
            status="connected", connected_by_user_id=user.id,
        )
        session.add(source)
        session.flush()
        root = LibraryService(session)._root(organization_id=organization_id, source=source)
        for index in range(20):
            session.add(LibraryNode(
                organization_id=organization_id, source_id=source.id, parent_id=root.id,
                external_id=f"empty-{index}", kind="folder", name=f"Empty {index}",
            ))

    reads = []

    def count_reads(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().lower().startswith("select") and "library_nodes" in statement:
            reads.append(statement)

    engine = factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", count_reads)
    try:
        with factory.begin() as session:
            LibraryService(session)._remove_empty_folders(source_id=source.id)
    finally:
        event.remove(engine, "before_cursor_execute", count_reads)
    with factory() as session:
        assert [node.id for node in session.scalars(select(LibraryNode))] == [root.id]
    assert len(reads) <= 4
