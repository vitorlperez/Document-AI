"""Unit coverage for bounded, tenant-scoped document-agent tools."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.ingestion.service import SyncAccessDenied
from app.knowledge.agent import AgentLimits, AgentService, ConversationService, ToolCall
from app.knowledge.models import Document
from app.knowledge.questions import AIProviderUnavailable
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


class FolderInventoryProvider(FakeProvider):
    def __init__(self, *, parent_id) -> None:
        super().__init__({})
        self.parent_id = parent_id

    def tool_calls(self, *, question, history, tool_results):
        return (
            [ToolCall("list_library_children", {"parent_id": str(self.parent_id)})]
            if not tool_results
            else []
        )


class FollowUpPluralProvider(FakeProvider):
    def tool_calls(self, *, question, history, tool_results):
        return [ToolCall("retrieve_evidence", {})] if not tool_results else []


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


def test_follow_up_plural_reuses_only_the_persisted_folder_inventory(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    organization, user, workspace = context(session)
    first = chunk(session, organization, workspace, name="A Gravidade.pdf", text="O texto discute graça.")
    second = chunk(session, organization, workspace, name="Profile.pdf", text="O perfil descreve experiência.")
    foreign = chunk(session, organization, workspace, name="Outro documento.pdf", text="Conteúdo alheio.")
    first_document = session.get(Document, first.document_id)
    second_document = session.get(Document, second.document_id)
    foreign_document = session.get(Document, foreign.document_id)
    assert first_document is not None and second_document is not None and foreign_document is not None
    root = LibraryNode(
        organization_id=organization.id, source_id=workspace.source_id, parent_id=None,
        external_id="source-root", kind="source", name="Google Drive",
    )
    session.add(root)
    session.flush()
    folder = LibraryNode(
        organization_id=organization.id, source_id=workspace.source_id, parent_id=root.id,
        external_id="test-document-ai", kind="folder", name="Test Document-AI",
    )
    session.add(folder)
    session.flush()
    session.add_all([
        LibraryNode(
            organization_id=organization.id, source_id=workspace.source_id, parent_id=folder.id,
            external_id=document.external_file_id, kind="file", name=document.name,
        )
        for document in (first_document, second_document)
    ] + [
        LibraryNode(
            organization_id=organization.id, source_id=workspace.source_id, parent_id=root.id,
            external_id=foreign_document.external_file_id, kind="file", name=foreign_document.name,
        )
    ])
    session.commit()

    scope = OrganizationScope(organization.id)
    inventory, _tool_results, references = AgentService(
        session, FolderInventoryProvider(parent_id=folder.id), AgentLimits()
    ).ask(
        scope=scope, user_id=user.id, question="Quais arquivos temos dentro dessa pasta?",
        providers=["google_drive"], mentions=[("folder", folder.id)], history=[],
    )
    assert inventory.answer == (
        "Arquivos no catálogo autorizado "
        "(instantâneo local; não é uma listagem ao vivo do provedor):\n"
        "- A Gravidade.pdf (Arquivo)\n"
        "- Profile.pdf (Arquivo)"
    )

    conversation, _ = ConversationService(session).create_or_load(
        scope=scope, user_id=user.id, conversation_id=None, question="Quais arquivos temos dentro dessa pasta?"
    )
    ConversationService(session).append(
        conversation=conversation, role="assistant", content=inventory.answer,
        context={"references": references},
    )
    session.commit()
    _conversation, history = ConversationService(session).history(
        scope=scope, user_id=user.id, conversation_id=conversation.id
    )
    follow_up = "me de um resumo bem sucinto do conteudo de cada arquivo"
    provider = FollowUpPluralProvider(
        {follow_up: [1.0, 0.0]},
        citations=[1, 2, 3],
    )

    result, _tool_results, follow_up_references = AgentService(session, provider, AgentLimits()).ask(
        scope=scope, user_id=user.id, question=follow_up,
        providers=["google_drive"], mentions=[], history=history,
    )
    assert provider.answer_calls == []
    assert "A Gravidade.pdf: Síntese extrativa" in result.answer
    assert "Profile.pdf: Síntese extrativa" in result.answer
    assert "Outro documento.pdf" not in result.answer
    assert {reference["name"] for reference in follow_up_references} == {
        "A Gravidade.pdf",
        "Profile.pdf",
    }
    with pytest.raises(SyncAccessDenied):
        AgentService(session, FakeProvider({}), AgentLimits()).ask(
            scope=scope, user_id=user.id, question=follow_up,
            providers=["notion"], mentions=[], history=history,
        )
    with pytest.raises(SyncAccessDenied):
        AgentService(session, FakeProvider({}), AgentLimits()).ask(
            scope=OrganizationScope(uuid4()), user_id=user.id, question=follow_up,
            providers=["google_drive"], mentions=[], history=history,
        )


def test_inventory_paginates_more_than_fifty_and_keeps_all_references(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    organization, user, workspace = context(session)
    root = LibraryNode(
        organization_id=organization.id, source_id=workspace.source_id, parent_id=None,
        external_id="source-root", kind="source", name="Google Drive",
    )
    session.add(root)
    session.flush()
    folder = LibraryNode(
        organization_id=organization.id, source_id=workspace.source_id, parent_id=root.id,
        external_id="briefs", kind="folder", name="Briefs",
    )
    session.add(folder)
    session.flush()
    indexed = chunk(session, organization, workspace, name="Brief 000.pdf", text="Primeiro arquivo.")
    indexed_document = session.get(Document, indexed.document_id)
    assert indexed_document is not None
    session.add_all([
        LibraryNode(
            organization_id=organization.id, source_id=workspace.source_id, parent_id=folder.id,
            external_id=(
                indexed_document.external_file_id if number == 0 else f"brief-{number}"
            ),
            kind="file", name=f"Brief {number:03d}.pdf",
        )
        for number in range(51)
    ])
    session.commit()

    result, _tool_results, references = AgentService(session, FakeProvider({}), AgentLimits()).ask(
        scope=OrganizationScope(organization.id), user_id=user.id,
        question="Quais arquivos temos dentro dessa pasta?",
        providers=["google_drive"], mentions=[("folder", folder.id)], history=[],
    )

    assert "Brief 050.pdf" in result.answer
    assert len(references) == 51
    assert {reference["folder_id"] for reference in references} == {str(folder.id)}


def test_inventory_includes_synchronized_nonindexed_file_and_plural_follow_up_is_per_file(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    organization, user, workspace = context(session)
    indexed = chunk(session, organization, workspace, name="Indexed.pdf", text="O plano prioriza clientes existentes.")
    indexed_document = session.get(Document, indexed.document_id)
    assert indexed_document is not None
    failed = Document(
        organization_id=organization.id,
        workspace_folder_id=workspace.id,
        external_file_id="failed-file",
        name="Not indexed.pdf",
        mime_type="application/pdf",
        source_url="https://drive.example.test/failed",
        content_hash="hash",
        processing_version="v1",
        index_status="failed",
    )
    root = LibraryNode(
        organization_id=organization.id, source_id=workspace.source_id, parent_id=None,
        external_id="source-root", kind="source", name="Google Drive",
    )
    session.add_all([failed, root])
    session.flush()
    folder = LibraryNode(
        organization_id=organization.id, source_id=workspace.source_id, parent_id=root.id,
        external_id="briefs", kind="folder", name="Briefs",
    )
    session.add(folder)
    session.flush()
    session.add_all([
        LibraryNode(
            organization_id=organization.id, source_id=workspace.source_id, parent_id=folder.id,
            external_id=indexed_document.external_file_id, kind="file", name="Indexed.pdf",
        ),
        LibraryNode(
            organization_id=organization.id, source_id=workspace.source_id, parent_id=folder.id,
            external_id=failed.external_file_id, kind="file", name="Not indexed.pdf",
        ),
    ])
    session.commit()
    scope = OrganizationScope(organization.id)
    inventory, _tool_results, references = AgentService(session, FakeProvider({}), AgentLimits()).ask(
        scope=scope, user_id=user.id, question="Quais arquivos temos dentro da pasta Briefs?",
        providers=["google_drive"], mentions=[("folder", folder.id)], history=[],
    )
    assert "Not indexed.pdf: sem conteúdo indexado disponível." in inventory.answer

    conversation, _ = ConversationService(session).create_or_load(
        scope=scope, user_id=user.id, conversation_id=None, question="inventário"
    )
    ConversationService(session).append(
        conversation=conversation, role="assistant", content=inventory.answer,
        context={"references": references},
    )
    session.commit()
    _conversation, history = ConversationService(session).history(
        scope=scope, user_id=user.id, conversation_id=conversation.id
    )
    result, _tool_results, _references = AgentService(session, FakeProvider({}), AgentLimits()).ask(
        scope=scope, user_id=user.id, question="Sobre o que eles falam?",
        providers=["google_drive"], mentions=[], history=history,
    )
    assert "Indexed.pdf: Síntese extrativa do conteúdo indexado: O plano prioriza clientes existentes." in result.answer
    assert "Not indexed.pdf: sem conteúdo indexado disponível." in result.answer

    moved = session.scalar(
        select(LibraryNode).where(
            LibraryNode.source_id == workspace.source_id,
            LibraryNode.external_id == indexed_document.external_file_id,
        )
    )
    assert moved is not None
    moved.parent_id = root.id
    session.commit()

    with pytest.raises(SyncAccessDenied, match="authorized selection"):
        AgentService(session, FakeProvider({}), AgentLimits()).ask(
            scope=scope, user_id=user.id, question="Sobre o que eles falam?",
            providers=["google_drive"], mentions=[], history=history,
        )


def test_inventory_applies_deadline_and_result_byte_limits(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    organization, user, workspace = context(session)
    root = LibraryNode(
        organization_id=organization.id, source_id=workspace.source_id, parent_id=None,
        external_id="source-root", kind="source", name="Google Drive",
    )
    session.add(root)
    session.flush()
    folder = LibraryNode(
        organization_id=organization.id, source_id=workspace.source_id, parent_id=root.id,
        external_id="briefs", kind="folder", name="Briefs",
    )
    session.add(folder)
    session.flush()
    indexed = chunk(session, organization, workspace, name="Brief.pdf", text="Brief content.")
    indexed_document = session.get(Document, indexed.document_id)
    assert indexed_document is not None
    session.add(LibraryNode(
        organization_id=organization.id, source_id=workspace.source_id, parent_id=folder.id,
        external_id=indexed_document.external_file_id, kind="file", name="Brief.pdf",
    ))
    session.commit()

    kwargs = {
        "scope": OrganizationScope(organization.id),
        "user_id": user.id,
        "question": "Quais arquivos temos dentro dessa pasta?",
        "providers": ["google_drive"],
        "mentions": [("folder", folder.id)],
        "history": [],
    }
    with pytest.raises(AIProviderUnavailable, match="deadline"):
        AgentService(session, FakeProvider({}), AgentLimits(max_seconds=0)).ask(**kwargs)
    with pytest.raises(AIProviderUnavailable, match="result exceeds"):
        AgentService(session, FakeProvider({}), AgentLimits(max_result_bytes=1)).ask(**kwargs)
