"""Selection and structured mention boundaries for the chat composer."""

from uuid import uuid4

import pytest

from app.knowledge.models import Document, DocumentChunk
from app.library.models import LibraryNode
from app.organizations.models import Membership
from app.workspaces.models import WorkspaceFolder
from tests.api.test_multiscope_questions_api import ask, corpus  # noqa: F401
from tests.api.test_text_search_api import search_api  # noqa: F401


@pytest.fixture()
def selection_nodes(corpus):  # noqa: F811
    client, factory, _, organization_id, folders, provider = corpus
    ids = {}
    with factory.begin() as session:
        for name, folder_id in folders.items():
            folder = session.get(WorkspaceFolder, folder_id)
            document = session.query(Document).filter_by(workspace_folder_id=folder_id).one()
            root = LibraryNode(
                organization_id=folder.organization_id, source_id=folder.source_id,
                external_id=f"{name}-root", kind="source", name=name,
            )
            session.add(root)
            session.flush()
            directory = LibraryNode(
                organization_id=folder.organization_id, source_id=folder.source_id,
                parent_id=root.id, external_id=f"{name}-directory", kind="folder", name="Campaign",
            )
            session.add(directory)
            session.flush()
            file = LibraryNode(
                organization_id=folder.organization_id, source_id=folder.source_id,
                parent_id=directory.id, external_id=document.external_file_id,
                kind="file", name=document.name,
            )
            session.add(file)
            session.flush()
            ids[name] = {"file": file.id, "folder": directory.id, "source": folder.source_id}
    return client, factory, organization_id, ids, provider


def selection(client, organization_id, providers, mentions=None):
    body = {"scope": "selection", "providers": providers}
    if mentions is not None:
        body["mentions"] = mentions
    return ask(client, organization_id, **body)


def mention(kind, node_id):
    return {"kind": kind, "node_id": str(node_id)}


def test_selection_unions_tools_and_filters_file_and_folder_mentions(selection_nodes):
    client, _, organization_id, ids, provider = selection_nodes
    both = selection(client, organization_id, ["google", "notion"])
    assert both.status_code == 200
    assert {item.source_provider for item in provider.answers[-1]} == {"google_drive", "notion"}
    assert both.json()["resolved_context"]["providers"] == ["google_drive", "notion"]

    only_file = selection(client, organization_id, ["google_drive", "notion"], [
        mention("file", ids["google_drive"]["file"])
    ])
    assert only_file.status_code == 200
    assert {item.source_provider for item in provider.answers[-1]} == {"google_drive"}
    assert {item["source_provider"] for item in only_file.json()["citations"]} == {"google_drive"}
    assert only_file.json()["resolved_context"]["document_count"] == 1

    both_mentions = selection(client, organization_id, ["google_drive", "notion"], [
        mention("folder", ids["google_drive"]["folder"]),
        mention("file", ids["notion"]["file"]),
    ])
    assert both_mentions.status_code == 200
    assert {item.source_provider for item in provider.answers[-1]} == {"google_drive", "notion"}


def test_selection_accepts_every_supported_tool_at_once(selection_nodes):
    client, _, organization_id, _, provider = selection_nodes
    every_tool = ["google_drive", "notion", "onedrive", "clickup"]
    response = selection(client, organization_id, every_tool)
    assert response.status_code == 200
    assert response.json()["resolved_context"]["providers"] == every_tool
    assert {item.source_provider for item in provider.answers[-1]} == {"google_drive", "notion"}


@pytest.mark.parametrize("invalid", [
    {"providers": []},
    {"providers": ["google", "google_drive"]},
    {"providers": ["notion", "notion"]},
    {"providers": ["google_drive", "notion", "onedrive", "clickup", "unknown"]},
    {"providers": ["unknown"]},
    {"providers": ["notion"], "provider": "notion"},
    {"providers": ["notion"], "mentions": [{"kind": "file", "node_id": "invalid"}]},
])
def test_invalid_selection_contract_stops_before_model(selection_nodes, invalid):
    client, _, organization_id, _, provider = selection_nodes
    response = ask(client, organization_id, scope="selection", **invalid)
    assert response.status_code == 422
    assert provider.embeds == provider.answers == []


def test_mentions_revalidate_type_provider_tenant_and_index(selection_nodes):
    client, factory, organization_id, ids, provider = selection_nodes
    file_id = ids["notion"]["file"]
    requests = [
        (["google_drive"], mention("file", file_id)),
        (["notion"], mention("folder", file_id)),
        (["notion"], mention("file", uuid4())),
    ]
    for providers, item in requests:
        assert selection(client, organization_id, providers, [item]).status_code == 422
    with factory.begin() as session:
        foreign = LibraryNode(
            organization_id=uuid4(), source_id=ids["notion"]["source"],
            external_id="foreign-file", kind="file", name="Secret.pdf",
        )
        session.add(foreign)
        session.flush()
        foreign_id = foreign.id
    assert selection(client, organization_id, ["notion"], [mention("file", foreign_id)]).status_code == 422
    with factory.begin() as session:
        document = session.query(Document).filter_by(external_file_id="notion").one()
        document.index_status = "failed"
    assert selection(client, organization_id, ["notion"], [mention("file", file_id)]).status_code == 422
    assert provider.embeds == provider.answers == []


def test_mention_candidates_only_show_indexed_own_nodes(selection_nodes):
    client, factory, organization_id, _, _ = selection_nodes
    response = client.get(f"/library/mention-candidates?organization_id={organization_id}&q=campaign")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 4
    assert {item["kind"] for item in items} == {"file", "folder"}
    assert all(item["path"].startswith(item["source_provider"]) for item in items)
    assert all("source_url" not in item for item in items)

    with factory.begin() as session:
        session.query(Membership).filter_by(organization_id=organization_id).update({"is_active": False})
    forbidden = client.get(f"/library/mention-candidates?organization_id={organization_id}&q=campaign")
    assert forbidden.status_code == 403
    assert "Campaign" not in forbidden.text


def test_selection_with_no_compatible_embeddings_never_calls_model(selection_nodes):
    client, factory, organization_id, ids, provider = selection_nodes
    with factory.begin() as session:
        session.query(DocumentChunk).update({"embedding": None, "embedding_model": None})
    response = selection(client, organization_id, ["google_drive"], [
        mention("file", ids["google_drive"]["file"])
    ])
    assert response.status_code == 200
    assert response.json()["retrieval_status"] == "no_compatible_embeddings"
    assert response.json()["answer"] is None
    assert provider.embeds == provider.answers == []


def test_mentioned_file_in_overlapping_folders_is_deduplicated(selection_nodes):
    client, factory, organization_id, ids, provider = selection_nodes
    with factory.begin() as session:
        original = session.query(Document).filter_by(external_file_id="google_drive").one()
        original_chunk = session.query(DocumentChunk).filter_by(document_id=original.id).one()
        original_folder = session.get(WorkspaceFolder, original.workspace_folder_id)
        overlap = WorkspaceFolder(
            organization_id=original.organization_id, source_id=original_folder.source_id,
            external_folder_id="overlap", name="Overlap", uniform_access_confirmed=True, status="ready",
        )
        session.add(overlap)
        session.flush()
        copy = Document(
            organization_id=original.organization_id, workspace_folder_id=overlap.id,
            external_file_id=original.external_file_id, name=original.name, mime_type=original.mime_type,
            source_url=original.source_url, content_hash="copy", processing_version="v1",
            index_status="indexed",
        )
        session.add(copy)
        session.flush()
        session.add(DocumentChunk(
            organization_id=original.organization_id, workspace_folder_id=overlap.id,
            document_id=copy.id, position=0, text=original_chunk.text,
            search_text=original_chunk.search_text, embedding=original_chunk.embedding,
            embedding_model=original_chunk.embedding_model,
        ))
    response = selection(client, organization_id, ["google_drive"], [
        mention("file", ids["google_drive"]["file"])
    ])
    assert response.status_code == 200
    assert len(provider.answers[-1]) == 1
    assert response.json()["resolved_context"]["document_count"] == 2
