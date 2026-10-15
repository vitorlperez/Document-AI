"""Contract: specs/library-indexing-status.md — per-file indexing state on library nodes."""
# ruff: noqa: F811  (pytest fixture imported from the library API tests)

from uuid import UUID

from app.knowledge.models import Document
from app.library.models import LibraryNode
from app.workspaces.models import WorkspaceFolder
from tests.api.test_company_library_api import api, login, seed_library  # noqa: F401


def add_file(session, *, organization, source, root, name, status=None, error_code=None, workspace=None):
    node = LibraryNode(
        organization_id=UUID(organization), source_id=UUID(source), parent_id=UUID(root),
        external_id=f"ext-{name}", kind="file", name=name, mime_type="application/pdf",
    )
    session.add(node)
    if status is not None:
        session.add(Document(
            organization_id=UUID(organization), workspace_folder_id=workspace.id,
            external_file_id=node.external_id, name=name, mime_type="application/pdf",
            source_url="", content_hash="h", processing_version="v1",
            index_status=status, error_code=error_code,
        ))
    return node


def children(client, organization, root):
    items = client.get(f"/library/nodes/{root}/children?organization_id={organization}").json()["items"]
    return {item["name"]: item for item in items}


def test_every_file_reports_state_and_reason(api):
    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    source = seed_library(factory, organization)
    root = client.get(f"/library?organization_id={organization}").json()["items"][0]["id"]
    with factory() as session:
        workspace = session.query(WorkspaceFolder).one()
        add_file(session, organization=organization, source=source, root=root, name="pending.pdf")
        add_file(session, organization=organization, source=source, root=root, name="failed.pdf",
                 status="failed", error_code="text_extraction_failed", workspace=workspace)
        add_file(session, organization=organization, source=source, root=root, name="video.mp4",
                 status="ignored", error_code="unsupported_file_type", workspace=workspace)
        add_file(session, organization=organization, source=source, root=root, name="empty.pdf",
                 status="skipped", error_code="empty_content", workspace=workspace)
        add_file(session, organization=organization, source=source, root=root, name="gone.pdf",
                 status="removed", workspace=workspace)
        session.add(LibraryNode(organization_id=UUID(organization), source_id=UUID(source),
                                parent_id=UUID(root), external_id="folder", kind="folder", name="Pasta"))
        session.commit()

    items = children(client, organization, root)

    indexing = {name: item["indexing"] for name, item in items.items() if "indexing" in item}
    assert {name: (value["state"], value["error_code"]) for name, value in indexing.items()} == {
        "Brief.pdf": ("indexed", None),
        "pending.pdf": ("pending", None),
        "failed.pdf": ("failed", "text_extraction_failed"),
        "video.mp4": ("ignored", "unsupported_file_type"),
        "empty.pdf": ("skipped", "empty_content"),
        "gone.pdf": ("not_found_in_source", None),
    }
    assert "indexing" not in items["Pasta"]
    assert indexing["Brief.pdf"]["document_id"] and indexing["Brief.pdf"]["workspace_folder_id"]
    assert indexing["pending.pdf"]["document_id"] is None
    assert set(indexing["Brief.pdf"]) == {"state", "error_code", "document_id", "workspace_folder_id", "indexed_at"}


def test_search_results_carry_the_same_state(api):
    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    source = seed_library(factory, organization)
    root = client.get(f"/library?organization_id={organization}").json()["items"][0]["id"]
    with factory() as session:
        add_file(session, organization=organization, source=source, root=root, name="Pendente.pdf")
        session.commit()

    items = client.get(f"/library/search?organization_id={organization}&query=pendente").json()["items"]

    assert [(item["name"], item["indexing"]["state"]) for item in items] == [("Pendente.pdf", "pending")]


def test_an_indexed_copy_in_any_workspace_wins_over_a_failure_in_another(api):
    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    source = seed_library(factory, organization)
    root = client.get(f"/library?organization_id={organization}").json()["items"][0]["id"]
    with factory() as session:
        other = WorkspaceFolder(organization_id=UUID(organization), source_id=UUID(source),
                                external_folder_id="other", name="Other", uniform_access_confirmed=True)
        session.add(other)
        session.flush()
        session.add(Document(
            organization_id=UUID(organization), workspace_folder_id=other.id, external_file_id="brief",
            name="Brief.pdf", mime_type="application/pdf", source_url="", content_hash="h",
            processing_version="v1", index_status="failed", error_code="file_too_large"))
        session.commit()

    assert children(client, organization, root)["Brief.pdf"]["indexing"]["state"] == "indexed"


def test_folder_nodes_report_robot_drive_access_state(api):
    from datetime import UTC, datetime, timedelta

    from app.identity.models import User
    from app.integrations.google_sa_models import DriveFolderLink

    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    source = seed_library(factory, organization)
    root = client.get(f"/library?organization_id={organization}").json()["items"][0]["id"]
    purge = datetime.now(UTC) + timedelta(days=9)
    with factory() as session:
        user = session.query(User).first()
        for external, status, after in (
            ("lost", "access_lost", purge), ("suspect", "suspect", purge),
            ("ok", "verified", None), ("scheduled", "purge_scheduled", purge),
        ):
            session.add(LibraryNode(organization_id=UUID(organization), source_id=UUID(source),
                                    parent_id=UUID(root), external_id=external, kind="folder", name=external))
            session.add(DriveFolderLink(
                organization_id=UUID(organization), data_source_id=UUID(source), external_folder_id=external,
                folder_name=external, status=status, purge_after=after, created_by_user_id=user.id))
        session.add(LibraryNode(organization_id=UUID(organization), source_id=UUID(source),
                                parent_id=UUID(root), external_id="plain", kind="folder", name="plain"))
        session.commit()

    items = children(client, organization, root)

    assert items["lost"]["access_state"] == "access_lost" and items["lost"]["purge_after"]
    assert items["suspect"]["access_state"] == "access_lost"
    assert items["scheduled"]["access_state"] == "purge_scheduled"
    assert "access_state" not in items["ok"] and "access_state" not in items["plain"]


def test_robot_drive_source_root_has_readable_name(api):
    from app.identity.models import User
    from app.integrations.models import DataSource
    from app.library.service import LibraryService

    client, factory = api
    login(client)
    organization = client.post("/organizations", json={"name": "Acme"}).json()["id"]
    seed_library(factory, organization)
    with factory() as session:
        user = session.query(User).first()
        source = DataSource(organization_id=UUID(organization), provider="google_drive_sa",
                            encrypted_credentials="x", status="connected", connected_by_user_id=user.id)
        session.add(source)
        session.flush()
        root = LibraryService(session)._root(organization_id=UUID(organization), source=source)
        assert root.name == "Google Drive"
