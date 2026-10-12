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
