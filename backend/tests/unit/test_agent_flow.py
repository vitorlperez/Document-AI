"""The single agent flow: classify -> tools -> grounded synthesis -> citations, and its safe fallbacks."""

import json
import time

import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.scoping import OrganizationScope
from app.ingestion.service import SyncAccessDenied
from app.knowledge.agent import (
    AgentLimits,
    AgentRun,
    AgentService,
    ConversationService,
    ConversationState,
    FlowModels,
    ToolResult,
)
from app.knowledge.agent_eval import load_cases, markdown_report, run_all
from app.knowledge.intent import (
    INTENT_SCHEMA,
    IntentDecision,
    InvalidIntent,
    fallback_intent,
    parse_intent,
)
from app.knowledge.models import Document
from app.knowledge.questions import (
    _REQUEST_DEADLINE,
    ANSWER_FORMAT_GUIDANCE,
    AIProviderUnavailable,
    Evidence,
    GeneratedAnswer,
    OpenAIQuestionProvider,
    QuestionResult,
)
from app.library.models import LibraryNode
from tests.unit.test_semantic_questions import FakeProvider, chunk, context
from tests.unit.test_semantic_questions import session as semantic_session  # noqa: F401

QUESTION = "Quais arquivos temos nessa pasta e me de uma explicacao resumida sobre o conteudo de cada arquivo"
RESTRUCTURE = "Estruture melhor o resumo do conteudo do arquivo"
INVENTORY_INTENT = {
    "intent": "list_files_with_summaries", "target": "mentioned", "ordinals": [],
    "tool": "list_folder_inventory", "query": "",
}


def _intent(intent: str, target: str = "mentioned", ordinals=(), tool: str = "none", query: str = "") -> dict:
    return {"intent": intent, "target": target, "ordinals": list(ordinals), "tool": tool, "query": query}


class IntentProvider(FakeProvider):
    """LLM mock: fixed classifier output and fixed synthesis."""

    def __init__(
        self, *, intent: object = INVENTORY_INTENT, synthesis: GeneratedAnswer | None = None,
        intent_error: Exception | None = None, vectors: dict[str, list[float]] | None = None,
        synthesis_error: Exception | None = None,
    ) -> None:
        super().__init__(vectors or {})
        self.intent = intent
        self.synthesis = synthesis or GeneratedAnswer(
            "Indexed.pdf trata da estratégia comercial: prioriza clientes existentes [1]. "
            "Not indexed.pdf ainda não tem conteúdo indexado.",
            [1],
        )
        self.intent_error = intent_error
        self.synthesis_error = synthesis_error
        self.intent_calls: list[dict[str, object]] = []
        self.synthesis_calls: list[dict[str, object]] = []

    def classify_intent(self, *, question, history, context, model="planner"):
        self.intent_calls.append({
            "question": question, "context": context, "model": model, "deadline": _REQUEST_DEADLINE.get(),
        })
        if self.intent_error is not None:
            raise self.intent_error
        return self.intent

    def synthesize_answer(self, *, question, intent, sources, catalog, model="synth", previous_answer=""):
        self.synthesis_calls.append({
            "intent": intent, "sources": sources, "catalog": catalog, "model": model,
            "previous_answer": previous_answer,
        })
        if self.synthesis_error is not None:
            raise self.synthesis_error
        return self.synthesis


def _folder_with_files(session: Session):
    organization, user, workspace = context(session)
    indexed = chunk(session, organization, workspace, name="Indexed.pdf", text="O plano prioriza clientes existentes.")
    document = session.get(Document, indexed.document_id)
    assert document is not None
    failed = Document(
        organization_id=organization.id, workspace_folder_id=workspace.id, external_file_id="failed-file",
        name="Not indexed.pdf", mime_type="application/pdf", source_url="https://drive.example.test/failed",
        content_hash="hash", processing_version="v1", index_status="failed",
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
            external_id=document.external_file_id, kind="file", name="Indexed.pdf",
        ),
        LibraryNode(
            organization_id=organization.id, source_id=workspace.source_id, parent_id=folder.id,
            external_id=failed.external_file_id, kind="file", name="Not indexed.pdf",
        ),
    ])
    session.commit()
    return OrganizationScope(organization.id), user, folder, document


def _ask(session, provider, folder, scope, user, *, models: FlowModels | None = None, limits=None):
    return AgentService(session, provider, limits or AgentLimits(), models=models).ask(
        scope=scope, user_id=user.id, question=QUESTION, providers=["google_drive"],
        mentions=[("folder", folder.id)], history=[],
    )


def _profile_library(session: Session):
    """Screenshot scenario: a library with A Gravidade.pdf and Profile.pdf."""
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
    return OrganizationScope(organization.id), user, profile_node, profile_document


def _history(session: Session, scope, user, turns: list[tuple[str, str, dict]]):
    conversation, _ = ConversationService(session).create_or_load(
        scope=scope, user_id=user.id, conversation_id=None, question=turns[0][1],
    )
    for role, content, message_context in turns:
        ConversationService(session).append(
            conversation=conversation, role=role, content=content, context=message_context,
        )
    session.commit()
    _conversation, history = ConversationService(session).history(
        scope=scope, user_id=user.id, conversation_id=conversation.id,
    )
    return history


def _linked(result) -> list[tuple[str, str]]:
    return [(item.document_name, item.source_url) for item in result.citations]


def _run(session, provider, scope, user, question, *, mentions, history=(), models=None):
    return AgentService(session, provider, AgentLimits(), models=models).ask(
        scope=scope, user_id=user.id, question=question, providers=["google_drive"],
        mentions=list(mentions), history=list(history),
    )


def test_unmentioned_profile_question_keeps_sources_when_answer_provider_times_out(
    semantic_session: Session, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    scope, user, _profile_node, profile_document = _profile_library(semantic_session)
    provider = IntentProvider(
        intent=_intent("ask_content", target="library", tool="retrieve_evidence"),
        vectors={"O que sabemos sobre o Vitor?": [0.0, 1.0]},
    )

    def timed_out_answer(*, question, evidence):
        raise AIProviderUnavailable("AI provider is unavailable")

    monkeypatch.setattr(provider, "answer", timed_out_answer)
    result, _tools, _references = _run(
        semantic_session, provider, scope, user, "O que sabemos sobre o Vitor?", mentions=[],
    )

    assert result.answer and "Software Engineer" in result.answer
    assert "síntese" in result.answer.casefold()
    assert _linked(result) == [("Profile.pdf", profile_document.source_url)]


def test_classifier_decides_inventory_with_summaries_and_synthesizes_with_sources(
    semantic_session: Session,  # noqa: F811
) -> None:
    scope, user, folder, document = _folder_with_files(semantic_session)
    provider = IntentProvider()

    result, tool_results, references = _ask(
        semantic_session, provider, folder, scope, user,
        models=FlowModels(planner_model="cheap", synthesis_model="final"),
    )

    [classified] = provider.intent_calls
    assert classified["model"] == "cheap"
    assert classified["context"]["mentioned_folders"] == 1
    [synthesis] = provider.synthesis_calls
    assert synthesis["model"] == "final"
    assert synthesis["intent"] == "list_files_with_summaries"
    assert [item.excerpt for item in synthesis["sources"]] == ["O plano prioriza clientes existentes."]
    assert synthesis["catalog"] == [
        {"name": "Indexed.pdf", "kind": "file", "index_status": "indexed"},
        {"name": "Not indexed.pdf", "kind": "file", "index_status": "not_indexed"},
    ]
    # Model-facing catalog never carries ids or URLs.
    assert "http" not in repr(synthesis["catalog"])
    assert result.answer == (
        "Indexed.pdf trata da estratégia comercial: prioriza clientes existentes (fonte 1). "
        "Not indexed.pdf ainda não tem conteúdo indexado."
    )
    assert [(item.document_id, item.source_url) for item in result.citations] == [
        (document.id, document.source_url)
    ]
    assert result.retrieval_status == "catalog"
    assert result.resolved_context == {
        "intent": "list_files_with_summaries", "decided_by": "llm",
        "target": "mentioned", "tools": ["list_library_children"],
    }
    assert [item["name"] for item in tool_results] == ["list_library_children"]
    assert {reference["name"] for reference in references} == {"Indexed.pdf", "Not indexed.pdf"}
    assert {reference["folder_id"] for reference in references} == {str(folder.id)}


def test_listing_intent_lists_without_synthesis_and_keeps_sources(semantic_session: Session) -> None:  # noqa: F811
    scope, user, folder, document = _folder_with_files(semantic_session)
    provider = IntentProvider(intent=_intent("list_files", tool="list_folder_inventory"))

    result, _tool_results, references = _run(
        semantic_session, provider, scope, user, "Quais arquivos temos dentro dessa pasta?",
        mentions=[("folder", folder.id)],
    )

    assert provider.synthesis_calls == []
    assert "Indexed.pdf" in result.answer and "Not indexed.pdf" in result.answer
    assert [(item.document_name, item.source_url) for item in result.citations] == [
        ("Indexed.pdf", document.source_url)
    ]
    assert result.resolved_context["intent"] == "list_files"
    assert [reference["name"] for reference in references] == ["Indexed.pdf", "Not indexed.pdf"]


def test_ordinal_summary_resolves_the_listed_file(semantic_session: Session) -> None:  # noqa: F811
    session = semantic_session
    organization, user, workspace = context(session)
    scope = OrganizationScope(organization.id)
    nodes = []
    root = LibraryNode(
        organization_id=organization.id, source_id=workspace.source_id, parent_id=None,
        external_id="source-root", kind="source", name="Google Drive",
    )
    session.add(root)
    session.flush()
    for name in ("First.pdf", "Second.pdf"):
        indexed = chunk(session, organization, workspace, name=name, text=f"{name} descreve o plano.")
        document = session.get(Document, indexed.document_id)
        assert document is not None
        node = LibraryNode(
            organization_id=organization.id, source_id=workspace.source_id, parent_id=root.id,
            external_id=document.external_file_id, kind="file", name=name,
        )
        session.add(node)
        nodes.append(node)
    session.commit()
    history = _history(session, scope, user, [
        ("user", "Liste os arquivos", {}),
        ("assistant", "Arquivos listados.", {"references": [
            {"id": str(node.id), "kind": "file", "name": node.name} for node in nodes
        ]}),
    ])
    provider = IntentProvider(intent=_intent("summarize_files", "previous_ordinals", [2], "summarize_documents"))

    result, _tool_results, _references = _run(
        session, provider, scope, user, "Resuma o segundo", mentions=[], history=history,
    )

    assert provider.intent_calls[0]["context"]["previous_answer_listed_files"] == ["First.pdf", "Second.pdf"]
    assert result.answer
    assert {item.document_name for item in result.citations} == {"Second.pdf"}
    assert all(item.source_url == "https://drive.example.test/Second.pdf" for item in result.citations)
    assert result.resolved_context["tools"] == ["summarize_documents"]
    assert result.resolved_context["target"] == "previous_ordinals"


@pytest.mark.parametrize("reattached", [True, False], ids=["file-mentioned-again", "file-from-previous-turn"])
def test_restructure_follow_up_reuses_history_and_mentioned_file(
    semantic_session: Session, reattached: bool,  # noqa: F811
) -> None:
    # Screenshot, second turn: "Estruture melhor o resumo do conteudo do arquivo" about Profile.pdf.
    scope, user, profile_node, profile_document = _profile_library(semantic_session)
    previous = "Profile.pdf descreve um engenheiro de software com experiência em Python (fonte 1)."
    history = _history(semantic_session, scope, user, [
        ("user", "Resuma o arquivo", {"mentions": [{"kind": "file", "node_id": str(profile_node.id)}]}),
        ("assistant", previous, {}),
    ])
    provider = IntentProvider(
        intent=_intent("restructure_previous", "mentioned" if reattached else "previous_turn_files",
                       tool="previous_answer"),
        synthesis=GeneratedAnswer(
            "## Perfil\n- Engenheiro de software com cinco anos de experiência [1].\n"
            "- Stack: Python, Django e FastAPI [1].",
            [1],
        ),
    )

    result, _tool_results, _references = _run(
        semantic_session, provider, scope, user, RESTRUCTURE,
        mentions=[("file", profile_node.id)] if reattached else [], history=history,
    )

    [synthesis] = provider.synthesis_calls
    assert synthesis["previous_answer"] == previous
    assert {item.document_name for item in synthesis["sources"]} == {"Profile.pdf"}
    assert result.answer.startswith("## Perfil")
    assert "(fonte 1)" in result.answer
    assert [(item.document_name, item.source_url) for item in result.citations] == [
        ("Profile.pdf", profile_document.source_url)
    ]
    assert result.confidence == "supported"
    assert result.resolved_context["intent"] == "restructure_previous"


def test_restructure_with_unverifiable_synthesis_uses_the_per_file_summary(
    semantic_session: Session,  # noqa: F811
) -> None:
    scope, user, profile_node, profile_document = _profile_library(semantic_session)
    history = _history(semantic_session, scope, user, [
        ("user", "Resuma o arquivo", {"mentions": [{"kind": "file", "node_id": str(profile_node.id)}]}),
        ("assistant", "Resumo anterior.", {}),
    ])
    provider = IntentProvider(
        intent=_intent("restructure_previous", tool="previous_answer"),
        synthesis=GeneratedAnswer("Texto sem nenhuma fonte.", []),
    )

    result, _tool_results, _references = _run(
        semantic_session, provider, scope, user, RESTRUCTURE,
        mentions=[("file", profile_node.id)], history=history,
    )

    assert result.answer and "Profile.pdf" in result.answer
    assert profile_document.source_url in {item.source_url for item in result.citations}
    assert result.resolved_context["tools"] == ["retrieve_evidence", "summarize_documents"]


def test_question_without_evidence_answers_honestly_with_sources(semantic_session: Session) -> None:  # noqa: F811
    scope, user, profile_node, profile_document = _profile_library(semantic_session)
    question = "Qual é a opinião dele sobre futebol?"
    provider = IntentProvider(
        intent=_intent("ask_content", tool="retrieve_evidence"),
        synthesis=GeneratedAnswer("Insufficient evidence.", []),
        vectors={question: [1.0, 0.0]},
    )

    result, _tool_results, _references = _run(
        semantic_session, provider, scope, user, question, mentions=[("file", profile_node.id)],
    )

    # The attached file's own text was offered to the synthesis before giving up.
    assert [item.document_name for item in provider.synthesis_calls[0]["sources"]] == ["Profile.pdf"]
    assert provider.answer_calls == []
    assert result.answer is not None
    assert "evidência suficiente" in result.answer and "Arquivos consultados" in result.answer
    assert "Profile.pdf (fonte 1)" in result.answer
    assert result.confidence == "insufficient_evidence"
    assert result.retrieval_status == "below_evidence_threshold"
    assert [(item.document_name, item.source_url) for item in result.citations] == [
        ("Profile.pdf", profile_document.source_url)
    ]


def test_fallback_without_evidence_never_returns_a_silent_empty_answer(
    semantic_session: Session,  # noqa: F811
) -> None:
    scope, user, profile_node, profile_document = _profile_library(semantic_session)
    question = "Qual é a opinião dele sobre futebol?"
    provider = IntentProvider(
        intent_error=AIProviderUnavailable("AI provider deadline exceeded"), vectors={question: [1.0, 0.0]},
        synthesis=GeneratedAnswer("Insufficient evidence.", []),
    )

    result, _tool_results, _references = _run(
        semantic_session, provider, scope, user, question, mentions=[("file", profile_node.id)],
    )

    assert result.resolved_context["decided_by"] == "fallback"
    assert result.answer is not None and "Arquivos consultados" in result.answer
    assert _linked(result) == [("Profile.pdf", profile_document.source_url)]


@pytest.mark.parametrize(
    "provider",
    [
        IntentProvider(intent_error=AIProviderUnavailable("AI provider deadline exceeded")),
        IntentProvider(intent_error=ValueError("malformed classifier JSON")),
        IntentProvider(intent=_intent("drop_tables")),
        IntentProvider(intent=_intent("summarize_files", "previous_ordinals", [7])),
        IntentProvider(intent=["not", "an", "object"]),
    ],
    ids=["classifier-timeout", "classifier-invalid-json", "unknown-intent", "ordinal-out-of-range", "not-object"],
)
def test_classifier_failures_fall_back_to_a_cited_relevance_search(
    semantic_session: Session, provider: IntentProvider,  # noqa: F811
) -> None:
    scope, user, folder, document = _folder_with_files(semantic_session)
    provider.vectors = {QUESTION: [1.0, 0.0]}

    result, tool_results, _references = _ask(semantic_session, provider, folder, scope, user)

    assert len(provider.intent_calls) == 1
    # No word list decides in the classifier's place: the attached folder is searched by relevance.
    assert result.resolved_context["decided_by"] == "fallback"
    assert result.resolved_context["intent"] == "ask_content"
    assert [item["name"] for item in tool_results] == ["retrieve_evidence"]
    assert provider.synthesis_calls == []
    assert result.answer
    assert _linked(result) == [("Indexed.pdf", document.source_url)]


def test_classifier_runs_under_its_own_short_deadline(semantic_session: Session) -> None:  # noqa: F811
    scope, user, folder, _document = _folder_with_files(semantic_session)
    provider = IntentProvider()
    before = time.monotonic()

    _ask(semantic_session, provider, folder, scope, user, models=FlowModels(intent_timeout_seconds=0.5))

    deadline = provider.intent_calls[0]["deadline"]
    assert deadline is not None and deadline <= before + 0.5 + 0.05


@pytest.mark.parametrize(
    "provider",
    [
        IntentProvider(synthesis=GeneratedAnswer("", [])),
        IntentProvider(synthesis=GeneratedAnswer("Insufficient evidence.", [])),
        IntentProvider(synthesis=GeneratedAnswer("Resposta sem fonte.", [])),
        IntentProvider(synthesis=GeneratedAnswer("Fonte inexistente [9].", [9])),
        IntentProvider(synthesis_error=AIProviderUnavailable("AI provider deadline exceeded")),
    ],
    ids=["empty", "insufficient", "uncited", "out-of-range", "synthesis-timeout"],
)
def test_unverifiable_synthesis_keeps_the_extractive_answer_with_sources(
    semantic_session: Session, provider: IntentProvider,  # noqa: F811
) -> None:
    scope, user, folder, document = _folder_with_files(semantic_session)

    result, _tool_results, _references = _ask(semantic_session, provider, folder, scope, user)

    assert "Síntese extrativa do conteúdo indexado" in result.answer
    assert "Fonte inexistente" not in result.answer
    assert [item.source_url for item in result.citations] == [document.source_url]
    assert result.resolved_context["decided_by"] == "llm"


def test_provider_without_classifier_answers_by_relevance_with_sources(
    semantic_session: Session,  # noqa: F811
) -> None:
    scope, user, folder, document = _folder_with_files(semantic_session)

    result, _tool_results, _references = _ask(
        semantic_session, FakeProvider({QUESTION: [1.0, 0.0]}), folder, scope, user,
    )

    assert result.resolved_context["decided_by"] == "fallback"
    assert result.answer
    assert _linked(result) == [("Indexed.pdf", document.source_url)]


def test_conversation_intent_uses_no_tools_unless_files_are_attached(semantic_session: Session) -> None:  # noqa: F811
    scope, user, profile_node, _document = _profile_library(semantic_session)
    provider = IntentProvider(intent=_intent("conversation", "library"))

    result, tool_results, _references = _run(semantic_session, provider, scope, user, "Obrigado!", mentions=[])

    # A fresh conversation used no document, so there is nothing to cite.
    assert tool_results == [] and result.citations == []
    assert result.retrieval_status == "conversation" and result.answer

    attached = IntentProvider(
        intent=_intent("conversation", "mentioned"), synthesis=GeneratedAnswer("Insufficient evidence.", []),
        vectors={"Oi, e esse aqui?": [0.0, 1.0]},
    )
    result, _tool_results, _references = _run(
        semantic_session, attached, scope, user, "Oi, e esse aqui?", mentions=[("file", profile_node.id)],
    )
    assert result.resolved_context["intent"] == "ask_content"
    assert {item.document_name for item in result.citations} == {"Profile.pdf"}


def test_conversation_reply_keeps_the_sources_of_the_conversation(semantic_session: Session) -> None:  # noqa: F811
    scope, user, profile_node, profile_document = _profile_library(semantic_session)
    history = _history(semantic_session, scope, user, [
        ("user", "Resuma o arquivo", {"mentions": [{"kind": "file", "node_id": str(profile_node.id)}]}),
        ("assistant", "Profile.pdf descreve um engenheiro de software (fonte 1).", {}),
    ])
    provider = IntentProvider(intent=_intent("conversation", "library"))

    result, tool_results, _references = _run(
        semantic_session, provider, scope, user, "Valeu, ficou ótimo!", mentions=[], history=history,
    )

    assert tool_results == []
    assert result.retrieval_status == "conversation" and "fontes abaixo" in result.answer
    # Re-read from the current catalog, so a revoked file would not come back as a source.
    assert _linked(result) == [("Profile.pdf", profile_document.source_url)]


def test_cite_backfills_the_documents_the_tools_read_when_the_answer_has_none() -> None:
    from uuid import uuid4

    read = Evidence(
        document_id=uuid4(), document_name="Plano.pdf", chunk_id=uuid4(), excerpt="Plano.",
        page_number=None, source_url="https://drive.example.test/Plano.pdf", score=1.0,
    )
    unlinked_copy = Evidence(
        document_id=read.document_id, document_name="Plano.pdf", chunk_id=uuid4(), excerpt="Outro trecho.",
        page_number=None, source_url="", score=0.5,
    )
    run = AgentRun(
        decision=IntentDecision(intent="list_files_with_summaries", target="mentioned"),
        intent="list_files_with_summaries", targets=[],
        conversation=ConversationState(listed_files=[], previous_turn_mentions=[], previous_answer=None),
        results=[ToolResult("list_library_children", {"items": []}, citations=(unlinked_copy, read))],
        answer=QuestionResult(
            answer="Texto da síntese sem marcadores.", confidence="supported", citations=[],
            retrieval_status="catalog",
        ),
    )

    cited = AgentService(None, FakeProvider({}), AgentLimits()).cite(run)

    assert cited.answer == "Texto da síntese sem marcadores."
    # One citation per document, and the one that carries the link.
    assert [(item.document_name, item.source_url) for item in cited.citations] == [
        ("Plano.pdf", "https://drive.example.test/Plano.pdf")
    ]


@pytest.mark.parametrize(
    ("intent", "tool"),
    [
        ("list_files", "list_folder_inventory"),
        ("list_files_with_summaries", "list_folder_inventory"),
        ("summarize_files", "summarize_documents"),
        ("ask_content", "retrieve_evidence"),
        ("restructure_previous", "previous_answer"),
        ("conversation", "none"),
    ],
)
def test_every_answer_that_used_documents_cites_them_with_links(
    semantic_session: Session, intent: str, tool: str,  # noqa: F811
) -> None:
    scope, user, profile_node, profile_document = _profile_library(semantic_session)
    question = "Sobre o que é este arquivo?"
    history = _history(semantic_session, scope, user, [
        ("user", "Resuma o arquivo", {"mentions": [{"kind": "file", "node_id": str(profile_node.id)}]}),
        ("assistant", "Profile.pdf descreve um engenheiro de software (fonte 1).", {}),
    ])
    provider = IntentProvider(
        intent=_intent(intent, tool=tool), vectors={question: [0.0, 1.0]},
        # A synthesis that cites nothing: the Fontes must still come from the documents the tools read.
        synthesis=GeneratedAnswer("Resposta sem marcador de fonte.", []),
    )

    result, _tool_results, _references = _run(
        semantic_session, provider, scope, user, question, mentions=[("file", profile_node.id)], history=history,
    )

    assert result.answer
    assert _linked(result) == [("Profile.pdf", profile_document.source_url)]


def test_authorization_errors_are_not_swallowed_by_fallback(semantic_session: Session) -> None:  # noqa: F811
    scope, user, folder, _document = _folder_with_files(semantic_session)
    provider = IntentProvider(intent_error=SyncAccessDenied("folder unavailable"))

    with pytest.raises(SyncAccessDenied):
        _ask(semantic_session, provider, folder, scope, user)


def test_parse_intent_enforces_the_closed_schema() -> None:
    decision = parse_intent(
        _intent("summarize_files", "previous_ordinals", [2, 2, 1], "search_library", "  contrato "),
        listed_files=3,
    )
    assert decision.ordinals == (2, 1)
    # A tool outside the intent's allowed set is replaced by the intent's default.
    assert decision.tool == "summarize_documents" and decision.query == ""
    assert parse_intent(_intent("list_files", "library", [3], "search_library", " Q3 "), listed_files=0).ordinals == ()
    assert parse_intent(_intent("list_files", "library", [], "search_library", " Q3 "), listed_files=0).query == "Q3"
    for raw in (
        _intent("unknown"), _intent("ask_content", "elsewhere"), _intent("ask_content", ordinals=["1"]),
        _intent("summarize_files", "previous_ordinals", []), _intent("summarize_files", "previous_ordinals", [4]),
        "text",
    ):
        with pytest.raises(InvalidIntent):
            parse_intent(raw, listed_files=3)
    assert INTENT_SCHEMA["required"] == ["intent", "target", "ordinals", "tool", "query"]


def test_fallback_decision_reads_only_what_is_attached() -> None:
    assert fallback_intent(has_mentions=True) == IntentDecision(
        intent="ask_content", target="mentioned", tool="retrieve_evidence", decided_by="fallback",
    )
    assert fallback_intent(has_mentions=False).target == "library"


def test_eval_harness_reports_intent_and_linked_sources(semantic_session: Session, tmp_path) -> None:  # noqa: F811
    scope, user, folder, _document = _folder_with_files(semantic_session)
    cases_file = tmp_path / "cases.json"
    cases_file.write_text(json.dumps([
        {
            "id": "inventory-with-summaries", "question": QUESTION, "providers": ["google_drive"],
            "mentions": [{"kind": "folder", "node_id": "$FOLDER"}], "must_mention": ["Indexed.pdf"],
        },
    ]))
    cases = load_cases(cases_file, folder_id=folder.id)

    [run] = run_all(
        semantic_session, IntentProvider(), cases, scope=scope, user_id=user.id,
        limits=AgentLimits(), models=FlowModels(),
    )

    assert (run.intent, run.decided_by, run.error) == ("list_files_with_summaries", "llm", None)
    assert run.citations == run.citations_with_link == 1
    assert run.answer_marks_sources and run.catalog_files_named == 2
    assert run.must_mention_hits == 1 and not run.answer_has_url
    assert "Classifier decided 1/1; answers with linked sources 1/1." in markdown_report([run])
    with pytest.raises(SystemExit):
        load_cases(cases_file, folder_id=None)


def test_settings_have_no_planner_flag() -> None:
    settings = Settings(database_url="postgresql://user:secret@localhost/db")
    assert not hasattr(settings, "agent_planner_enabled")
    assert settings.agent_intent_timeout_seconds == 4.0
    assert FlowModels().intent_timeout_seconds == 4.0


def _responses_envelope(payload: object) -> dict[str, object]:
    return {"output": [{"content": [{"type": "output_text", "text": json.dumps(payload)}]}]}


def test_openai_intent_classifier_is_deterministic_and_schema_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OpenAIQuestionProvider("key")
    bodies: list[dict[str, object]] = []
    replies = iter([
        _responses_envelope(INVENTORY_INTENT),
        _responses_envelope(INVENTORY_INTENT),
        _responses_envelope({"answer": "Resumo [1].", "citations": [1]}),
        {"output": [{"content": [{"type": "output_text", "text": "not json"}]}]},
    ])

    def fake_post(path, body):
        bodies.append(body)
        return next(replies)

    monkeypatch.setattr(provider, "_post", fake_post)
    decided = provider.classify_intent(question=QUESTION, history=[], context={}, model="gpt-5-nano")
    provider.classify_intent(question=QUESTION, history=[], context={}, model="gpt-4.1-nano")
    answer = provider.synthesize_answer(
        question=RESTRUCTURE, intent="restructure_previous", sources=[], catalog=[], model="final",
        previous_answer="Resumo anterior.",
    )
    invalid = provider.synthesize_answer(question=QUESTION, intent="list_files", sources=[], catalog=[])

    assert decided == INVENTORY_INTENT
    assert answer == GeneratedAnswer("Resumo [1].", [1])
    assert invalid == GeneratedAnswer("", [])
    assert [body["model"] for body in bodies] == ["gpt-5-nano", "gpt-4.1-nano", "final", "gpt-5-mini"]
    schema_format = bodies[0]["text"]["format"]
    assert schema_format["strict"] is True and schema_format["schema"] == INTENT_SCHEMA
    # Reasoning models reject temperature; minimal effort is their deterministic setting.
    assert bodies[0]["reasoning"] == {"effort": "minimal"} and "temperature" not in bodies[0]
    assert bodies[1]["temperature"] == 0
    assert '"previous_answer": "Resumo anterior."' in bodies[2]["input"]
    assert "previous_answer" not in bodies[3]["input"]
    assert "URL" in bodies[2]["instructions"]
    assert ANSWER_FORMAT_GUIDANCE in bodies[2]["instructions"]
    assert ANSWER_FORMAT_GUIDANCE in bodies[3]["instructions"]


def test_intent_eval_set_runs_against_a_mocked_classifier() -> None:
    from pathlib import Path

    from app.knowledge.intent_eval import markdown_report, run_cases

    cases = json.loads(Path("scripts/intent_eval_cases.json").read_text(encoding="utf-8"))

    class EchoClassifier:
        """Answers each case with its expected decision, plus one failure, to exercise the scoring."""

        def classify_intent(self, *, question, history, context, model):
            case = next(item for item in cases if item["question"] == question)
            if case["id"] == "greeting":
                raise ValueError("malformed")
            expected = case["expect"]
            return _intent(expected["intent"], expected["target"], expected.get("ordinals", []))

    runs = run_cases(EchoClassifier(), cases, model="mock")

    assert len(runs) == len(cases) >= 20
    assert [run.case_id for run in runs if not run.correct] == ["greeting"]
    assert f"Accuracy: {len(cases) - 1}/{len(cases)}" in markdown_report(runs)


def test_parse_intent_normalizes_targets_the_agent_resolves_the_same_way() -> None:
    assert parse_intent(_intent("restructure_previous", "previous_turn_files"), listed_files=0, mentioned=1).target == (
        "mentioned"
    )
    assert parse_intent(_intent("list_files", "library"), listed_files=0, mentioned=1).target == "mentioned"
    assert parse_intent(_intent("summarize_files", "previous_answer_files"), listed_files=0).target == (
        "previous_turn_files"
    )
    assert parse_intent(_intent("summarize_files", "previous_ordinals", [1]), listed_files=2, mentioned=1).target == (
        "previous_ordinals"
    )
