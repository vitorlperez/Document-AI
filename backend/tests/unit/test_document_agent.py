"""Unit coverage for bounded, tenant-scoped document-agent tools."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.ingestion.service import SyncAccessDenied
from app.knowledge.agent import AgentLimits, AgentService, ConversationService
from app.knowledge.models import Document
from app.knowledge.questions import AIProviderUnavailable
from app.library.models import LibraryNode
from tests.unit.test_semantic_questions import FakeProvider, chunk, context
from tests.unit.test_semantic_questions import session as semantic_session  # noqa: F401


class Classifies(FakeProvider):
    """Mocked intent classifier with a fixed decision; no synthesis model."""

    def __init__(self, vectors=None, *, intent: str, target: str = "mentioned", ordinals=(), tool: str = "none",
                 query: str = "", extra: dict | None = None, **kwargs) -> None:
        super().__init__(vectors or {}, **kwargs)
        self.decision = {
            "intent": intent, "target": target, "ordinals": list(ordinals), "tool": tool, "query": query,
            **(extra or {}),
        }
        self.intent_calls = 0

    def classify_intent(self, *, question, history, context, model="gpt-5-nano"):
        self.intent_calls += 1
        self.last_context = context
        self.last_history = history
        return self.decision


def list_folder() -> Classifies:
    return Classifies(intent="list_files", tool="list_folder_inventory")


def test_cited_sources_become_follow_up_file_targets_without_a_folder_mention(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    organization, user, workspace = context(session)
    documents = [
        chunk(session, organization, workspace, name="Vitor Resume.pdf",
              text="Vitor trabalha com Python e Django."),
        chunk(session, organization, workspace, name="Vitor Profile.pdf",
              text="Vitor desenvolve sistemas de IA e usa FastAPI."),
    ]
    root = LibraryNode(
        organization_id=organization.id, source_id=workspace.source_id, parent_id=None,
        external_id="root", kind="source", name="Google Drive",
    )
    session.add(root)
    session.flush()
    for item in documents:
        document = session.get(Document, item.document_id)
        assert document is not None
        session.add(LibraryNode(
            organization_id=organization.id, source_id=workspace.source_id, parent_id=root.id,
            external_id=document.external_file_id, kind="file", name=document.name,
        ))
    session.commit()
    scope = OrganizationScope(organization.id)
    first_question = "O que sabemos sobre o Vitor?"
    first_model = Classifies({first_question: [1.0, 0.0]}, intent="ask_content", target="library",
                             tool="retrieve_evidence", answer="Vitor trabalha com Python e IA.",
                             citations=[1, 2])
    first, _, references = AgentService(session, first_model, AgentLimits()).ask(
        scope=scope, user_id=user.id, question=first_question,
        providers=["google_drive"], mentions=[], history=[],
    )
    assert first.answer and len({item.document_id for item in first.citations}) == 2
    assert references == []
    conversation, _ = ConversationService(session).create_or_load(
        scope=scope, user_id=user.id, conversation_id=None, question=first_question,
    )
    ConversationService(session).append(conversation=conversation, role="user", content=first_question,
                                        context={"mentions": []})
    ConversationService(session).append(
        conversation=conversation, role="assistant", content=first.answer,
        context={"references": references},
        response={"citations": [{"document_id": str(item.document_id)} for item in first.citations]},
    )
    session.commit()
    _, history = ConversationService(session).history(
        scope=scope, user_id=user.id, conversation_id=conversation.id,
    )
    follow_up = "Me de um resumo por aquivo do conteudo e o que fala sobre o Vitor"
    second_model = Classifies(intent="summarize_files", target="previous_answer_files",
                              tool="summarize_documents")
    second, tools, _ = AgentService(session, second_model, AgentLimits()).ask(
        scope=scope, user_id=user.id, question=follow_up,
        providers=["google_drive"], mentions=[], history=history,
    )
    assert set(second_model.last_context["previous_answer_listed_files"]) == {
        "Vitor Resume.pdf", "Vitor Profile.pdf",
    }
    assert second_model.last_history[-1]["content"] == first.answer
    assert second.resolved_context["target"] == "previous_answer_files"
    assert second.resolved_context.get("fallback") is None
    assert [item["name"] for item in tools] == ["summarize_inventory"]
    assert second.answer and "Vitor Resume.pdf" in second.answer and "Vitor Profile.pdf" in second.answer
    assert {item.document_name for item in second.citations} == {"Vitor Resume.pdf", "Vitor Profile.pdf"}
    assert all(item.source_url for item in second.citations)


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


def test_name_search_lists_matches_with_linked_sources(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    organization, user, workspace = context(session)
    text = "The launch is documented in the project brief."
    indexed = chunk(session, organization, workspace, name="Brief.pdf", text=text)
    document = session.get(Document, indexed.document_id)
    assert document is not None
    session.add(LibraryNode(
        organization_id=organization.id, source_id=workspace.source_id, parent_id=None,
        external_id=document.external_file_id, kind="file", name="Brief.pdf",
    ))
    session.commit()
    provider = Classifies(intent="list_files", target="library", tool="search_library", query="brief")

    result, tool_results, references = AgentService(
        session, provider, AgentLimits(max_result_bytes=10_000, max_seconds=10)
    ).ask(
        scope=OrganizationScope(organization.id), user_id=user.id, question="Tem algum arquivo chamado brief?",
        providers=["google_drive"], mentions=[], history=[],
    )

    assert provider.intent_calls == 1
    assert [item["name"] for item in tool_results] == ["search_library"]
    assert result.answer == "Itens encontrados no catálogo autorizado:\n- Brief.pdf (Arquivo)"
    assert references == [{"id": str(tool_results[-1]["result"]["items"][0]["id"]), "kind": "file", "name": "Brief.pdf"}]
    assert [(item.document_name, item.source_url) for item in result.citations] == [("Brief.pdf", document.source_url)]


def test_classifier_output_never_overrides_authorized_request_scope(
    semantic_session: Session,  # noqa: F811
) -> None:
    session = semantic_session
    organization, user, workspace = context(session)
    text = "Private project scope."
    chunk(session, organization, workspace, name="Scope.pdf", text=text)
    provider = Classifies(
        {"What is the scope?": [1.0, 0.0]}, intent="ask_content", target="library", tool="retrieve_evidence",
        extra={"providers": ["foreign"], "organization_id": str(uuid4())},
    )

    result, _tool_results, _references = AgentService(session, provider, AgentLimits()).ask(
        scope=OrganizationScope(organization.id), user_id=user.id, question="What is the scope?",
        providers=["google_drive"], mentions=[], history=[],
    )

    assert {item.document_name for item in result.citations} == {"Scope.pdf"}
    assert all(item.source_url for item in result.citations)


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
    provider = Classifies(
        {"Resuma o segundo": [1.0, 0.0]}, intent="summarize_files", target="previous_ordinals", ordinals=[2],
        tool="summarize_documents",
    )

    result, _tool_results, _references = AgentService(session, provider, AgentLimits()).ask(
        scope=OrganizationScope(organization.id), user_id=user.id, question="Resuma o segundo",
        providers=["google_drive"], mentions=[], history=history,
    )

    assert result.citations
    assert {item.document_name for item in result.citations} == {"Second.pdf"}
    assert {item.source_url for item in result.citations} == {second_document.source_url}


def test_follow_up_each_file_reuses_only_the_persisted_folder_inventory(
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
    inventory, _tool_results, references = AgentService(session, list_folder(), AgentLimits()).ask(
        scope=scope, user_id=user.id, question="Quais arquivos temos dentro dessa pasta?",
        providers=["google_drive"], mentions=[("folder", folder.id)], history=[],
    )
    assert inventory.answer == (
        "Arquivos no catálogo autorizado "
        "(instantâneo local; não é uma listagem ao vivo do provedor):\n"
        "- A Gravidade.pdf (Arquivo)\n"
        "- Profile.pdf (Arquivo)"
    )
    assert {item.document_name for item in inventory.citations} == {"A Gravidade.pdf", "Profile.pdf"}

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

    def each_file():
        return Classifies(
            {follow_up: [1.0, 0.0]}, intent="summarize_files", target="previous_answer_files",
            tool="summarize_documents",
        )

    result, _tool_results, _references = AgentService(session, each_file(), AgentLimits()).ask(
        scope=scope, user_id=user.id, question=follow_up,
        providers=["google_drive"], mentions=[], history=history,
    )
    assert result.answer and "Outro documento.pdf" not in result.answer
    assert {item.document_name for item in result.citations} <= {"A Gravidade.pdf", "Profile.pdf"}
    assert result.citations and all(item.source_url for item in result.citations)
    assert result.resolved_context["target"] == "previous_answer_files"

    with pytest.raises(SyncAccessDenied):
        AgentService(session, each_file(), AgentLimits()).ask(
            scope=scope, user_id=user.id, question=follow_up,
            providers=["notion"], mentions=[], history=history,
        )
    with pytest.raises(SyncAccessDenied):
        AgentService(session, each_file(), AgentLimits()).ask(
            scope=OrganizationScope(uuid4()), user_id=user.id, question=follow_up,
            providers=["google_drive"], mentions=[], history=history,
        )

    moved = session.scalar(
        select(LibraryNode).where(
            LibraryNode.source_id == workspace.source_id,
            LibraryNode.external_id == second_document.external_file_id,
        )
    )
    assert moved is not None
    moved.parent_id = root.id
    session.commit()
    # A file reused from the listing must still be inside the listed folder.
    with pytest.raises(SyncAccessDenied, match="authorized selection"):
        AgentService(session, each_file(), AgentLimits()).ask(
            scope=scope, user_id=user.id, question=follow_up,
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

    result, _tool_results, references = AgentService(session, list_folder(), AgentLimits()).ask(
        scope=OrganizationScope(organization.id), user_id=user.id,
        question="Quais arquivos temos dentro dessa pasta?",
        providers=["google_drive"], mentions=[("folder", folder.id)], history=[],
    )

    assert "Brief 050.pdf" in result.answer
    assert len(references) == 51
    assert {reference["folder_id"] for reference in references} == {str(folder.id)}


def test_inventory_includes_synchronized_nonindexed_file_and_each_file_follow_up_is_cited(
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
    inventory, _tool_results, references = AgentService(session, list_folder(), AgentLimits()).ask(
        scope=scope, user_id=user.id, question="Quais arquivos temos dentro da pasta Briefs?",
        providers=["google_drive"], mentions=[("folder", folder.id)], history=[],
    )
    assert "Not indexed.pdf: sem conteúdo indexado disponível." in inventory.answer
    assert [(item.document_name, item.source_url) for item in inventory.citations] == [
        ("Indexed.pdf", indexed_document.source_url)
    ]
    assert "Indexed.pdf (Arquivo)" in inventory.answer
    assert "Síntese extrativa" not in inventory.answer

    summarized_inventory, _tool_results, summarized_references = AgentService(
        session, Classifies(intent="list_files_with_summaries", tool="list_folder_inventory"), AgentLimits()
    ).ask(
        scope=scope, user_id=user.id,
        question="Quais arquivos temos nessa pasta e me de uma explicacao resumida sobre o conteudo de cada arquivo",
        providers=["google_drive"], mentions=[("folder", folder.id)], history=[],
    )
    assert summarized_inventory.retrieval_status == "catalog"
    assert (
        "Indexed.pdf: Síntese extrativa do conteúdo indexado: O plano prioriza clientes existentes."
        in summarized_inventory.answer
    )
    assert "Not indexed.pdf: sem conteúdo indexado disponível." in summarized_inventory.answer
    assert [(item.document_id, item.source_url) for item in summarized_inventory.citations] == [
        (indexed_document.id, indexed_document.source_url)
    ]
    assert summarized_references == references

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
    result, _tool_results, _references = AgentService(
        session,
        Classifies(
            {"Sobre o que eles falam?": [1.0, 0.0]}, intent="summarize_files", target="previous_answer_files",
            tool="summarize_documents",
        ),
        AgentLimits(),
    ).ask(
        scope=scope, user_id=user.id, question="Sobre o que eles falam?",
        providers=["google_drive"], mentions=[], history=history,
    )
    assert result.answer
    assert [(item.document_id, item.source_url) for item in result.citations] == [
        (indexed_document.id, indexed_document.source_url)
    ]


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
        AgentService(session, list_folder(), AgentLimits(max_seconds=0)).ask(**kwargs)
    with pytest.raises(AIProviderUnavailable, match="result exceeds"):
        AgentService(session, list_folder(), AgentLimits(max_result_bytes=1)).ask(**kwargs)


def test_file_mention_restructure_summary_answers_instead_of_insufficient_evidence(
    semantic_session: Session,  # noqa: F811
) -> None:
    # Reported chat, second turn: "Estruture melhor o resumo do conteudo do arquivo"
    # with the file Profile.pdf mentioned came back with answer=None
    # (below_evidence_threshold), shown as "Não encontrei evidência suficiente".
    session = semantic_session
    organization, user, workspace = context(session)
    chunk(session, organization, workspace, name="A Gravidade.pdf", text="O texto discute graça.")
    profile = chunk(
        session, organization, workspace, name="Profile.pdf",
        text="Software Engineer com cinco anos de experiência em Python, Django e FastAPI.",
        embedding=[0.0, 1.0],
    )
    profile_document = session.get(Document, profile.document_id)
    assert profile_document is not None
    root = LibraryNode(
        organization_id=organization.id, source_id=workspace.source_id, parent_id=None,
        external_id="source-root", kind="source", name="Google Drive",
    )
    session.add(root)
    session.flush()
    profile_node = LibraryNode(
        organization_id=organization.id, source_id=workspace.source_id, parent_id=root.id,
        external_id=profile_document.external_file_id, kind="file", name="Profile.pdf",
    )
    session.add(profile_node)
    session.commit()
    question = "Estruture melhor o resumo do conteudo do arquivo"
    # First turn of the chat: the classifier asks for the file's summary (no earlier answer to restructure).
    provider = Classifies({question: [1.0, 0.0]}, intent="restructure_previous", tool="previous_answer")

    result, _tool_results, _references = AgentService(session, provider, AgentLimits()).ask(
        scope=OrganizationScope(organization.id), user_id=user.id, question=question,
        providers=["google_drive"], mentions=[("file", profile_node.id)], history=[],
    )

    assert result.answer
    assert result.retrieval_status == "sufficient_evidence"
    assert "cinco anos de experiência em Python" in result.answer
    assert {item.document_name for item in result.citations} == {"Profile.pdf"}
    assert all(item.source_url for item in result.citations)
