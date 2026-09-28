"""Unit coverage for bounded, tenant-scoped document-agent tools."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.ingestion.service import SyncAccessDenied
from app.knowledge.agent import AgentLimits, AgentService, ConversationService, ToolCall
from app.knowledge.models import Document
from app.library.models import LibraryNode
from tests.unit.test_semantic_questions import FakeProvider, chunk, context
from tests.unit.test_semantic_questions import session as semantic_session  # noqa: F401


class RepeatingCatalogProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__({"What is documented?": [1.0, 0.0]})
        self.calls = 0

    def tool_calls(self, *, question, history, tool_results):
        self.calls += 1
        return [ToolCall("search_library", {"query": "brief"})]


class SummarizeSecondProvider(FakeProvider):
    def tool_calls(self, *, question, history, tool_results):
        return [ToolCall("summarize_documents", {})] if not tool_results else []


def test_direct_children_tool_is_paged_local_catalog_snapshot(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    organization, user, workspace = context(session)
    parent = LibraryNode(
        organization_id=organization.id, source_id=workspace.source_id, parent_id=None,
        external_id="folder", kind="folder", name="Briefs",
    )
    session.add(parent)
    session.flush()
    session.add_all([
        LibraryNode(
            organization_id=organization.id, source_id=workspace.source_id, parent_id=parent.id,
            external_id=f"file-{number}", kind="file", name=f"Brief {number}.pdf",
        )
        for number in range(3)
    ])
    session.commit()

    provider = FakeProvider({})
    result = AgentService(session, provider, AgentLimits()).tools.list_library_children(
        scope=OrganizationScope(organization.id), user_id=user.id, providers=["google_drive"], mentions=[],
        parent_id=parent.id, page=2, page_size=2,
    )

    assert result.payload["semantics"] == "direct_children_local_catalog_snapshot"
    assert result.payload["total"] == 3
    assert [item["name"] for item in result.payload["items"]] == ["Brief 2.pdf"]


def test_catalog_tool_result_becomes_the_final_inventory_answer(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    organization, user, workspace = context(session)
    text = "The launch is documented in the project brief."
    chunk(session, organization, workspace, name="Brief.pdf", text=text)
    session.add(LibraryNode(
        organization_id=organization.id, source_id=workspace.source_id, parent_id=None,
        external_id="brief-node", kind="file", name="Brief.pdf",
    ))
    session.commit()
    provider = RepeatingCatalogProvider()

    result, tool_results, references = AgentService(
        session, provider, AgentLimits(max_steps=2, max_result_bytes=10_000, max_seconds=10)
    ).ask(
        scope=OrganizationScope(organization.id), user_id=user.id, question="What is documented?",
        providers=["google_drive"], mentions=[], history=[],
    )

    assert provider.calls == 2
    assert [item["name"] for item in tool_results] == ["search_library", "search_library"]
    assert result.answer == "Itens encontrados no catálogo autorizado:\n- Brief.pdf (Arquivo)"
    assert references == [{"id": str(tool_results[-1]["result"]["items"][0]["id"]), "kind": "file", "name": "Brief.pdf"}]


def test_tool_arguments_never_override_authorized_request_scope(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    organization, user, workspace = context(session)
    text = "Private project scope."
    chunk(session, organization, workspace, name="Scope.pdf", text=text)
    provider = FakeProvider({"What is the scope?": [1.0, 0.0]})
    service = AgentService(session, provider, AgentLimits())

    result = service._execute(
        call=ToolCall("retrieve_evidence", {"providers": ["foreign"], "organization_id": str(uuid4())}),
        scope=OrganizationScope(organization.id), user_id=user.id, question="What is the scope?",
        providers=["google_drive"], mentions=[],
    )

    assert result.question_result is not None
    assert result.question_result.citations


def test_conversation_history_is_user_and_organization_isolated(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    organization, user, _workspace = context(session)
    conversations = ConversationService(session)
    conversation, _ = conversations.create_or_load(
        scope=OrganizationScope(organization.id), user_id=user.id, conversation_id=None, question="First"
    )
    conversations.append(conversation=conversation, role="user", content="First", context={"providers": []})
    conversations.append(conversation=conversation, role="assistant", content="Second", context={})
    session.commit()

    loaded, history = conversations.history(
        scope=OrganizationScope(organization.id), user_id=user.id, conversation_id=conversation.id
    )
    assert loaded.id == conversation.id
    assert [(message.position, message.content) for message in history] == [(1, "First"), (2, "Second")]

    with pytest.raises(SyncAccessDenied):
        conversations.history(
            scope=OrganizationScope(organization.id), user_id=uuid4(), conversation_id=conversation.id
        )


def test_follow_up_ordinal_uses_persisted_reference_and_reauthorizes_it(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    organization, user, workspace = context(session)
    first = chunk(session, organization, workspace, name="First.pdf", text="First document.")
    second = chunk(session, organization, workspace, name="Second.pdf", text="Second document.")
    first_document = session.get(Document, first.document_id)
    second_document = session.get(Document, second.document_id)
    assert first_document is not None and second_document is not None
    root = LibraryNode(
        organization_id=organization.id, source_id=workspace.source_id, parent_id=None,
        external_id="source-root", kind="source", name="Google Drive",
    )
    session.add(root)
    session.flush()
    first_node = LibraryNode(
        organization_id=organization.id, source_id=workspace.source_id, parent_id=root.id,
        external_id=first_document.external_file_id, kind="file", name="First.pdf",
    )
    second_node = LibraryNode(
        organization_id=organization.id, source_id=workspace.source_id, parent_id=root.id,
        external_id=second_document.external_file_id, kind="file", name="Second.pdf",
    )
    session.add_all([first_node, second_node])
    conversation, _ = ConversationService(session).create_or_load(
        scope=OrganizationScope(organization.id), user_id=user.id, conversation_id=None, question="Liste os arquivos"
    )
    ConversationService(session).append(
        conversation=conversation, role="assistant", content="Arquivos listados.",
        context={"references": [
            {"id": str(first_node.id), "kind": "file", "name": "First.pdf"},
            {"id": str(second_node.id), "kind": "file", "name": "Second.pdf"},
        ]},
    )
    session.commit()
    _conversation, history = ConversationService(session).history(
        scope=OrganizationScope(organization.id), user_id=user.id, conversation_id=conversation.id
    )
    provider = SummarizeSecondProvider({"Resuma o segundo": [1.0, 0.0]})

    result, _tool_results, _references = AgentService(session, provider, AgentLimits()).ask(
        scope=OrganizationScope(organization.id), user_id=user.id, question="Resuma o segundo",
        providers=["google_drive"], mentions=[], history=history,
    )

    assert result.citations
    assert [item.document_name for item in provider.answer_calls[-1][1]] == ["Second.pdf"]
