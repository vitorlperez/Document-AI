"""Flag-gated planner -> tools -> synthesis flow and its fallback to the current path."""

import json

import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.scoping import OrganizationScope
from app.ingestion.service import SyncAccessDenied
from app.knowledge.agent import (
    AgentLimits,
    AgentService,
    ConversationService,
    PlannedFlow,
    PlannedFlowRejected,
    PlannedStep,
    _parse_plan,
)
from app.knowledge.agent_eval import compare, load_cases, markdown_report
from app.knowledge.models import Document
from app.knowledge.questions import AIProviderUnavailable, GeneratedAnswer, OpenAIQuestionProvider
from app.library.models import LibraryNode
from tests.unit.test_semantic_questions import FakeProvider, chunk, context
from tests.unit.test_semantic_questions import session as semantic_session  # noqa: F401

QUESTION = "Quais arquivos temos nessa pasta e me de uma explicacao resumida sobre o conteudo de cada arquivo"
INVENTORY_PLAN = {"intent": "inventory_with_summaries", "tools": [{"name": "list_folder_inventory", "query": ""}]}


class PlanningProvider(FakeProvider):
    def __init__(
        self, *, plan: object = INVENTORY_PLAN, synthesis: GeneratedAnswer | None = None,
        plan_error: Exception | None = None,
    ) -> None:
        super().__init__({})
        self.plan = plan
        self.synthesis = synthesis or GeneratedAnswer(
            "Indexed.pdf trata da estratégia comercial: prioriza clientes existentes [1]. "
            "Not indexed.pdf ainda não tem conteúdo indexado.",
            [1],
        )
        self.plan_error = plan_error
        self.plan_calls: list[dict[str, object]] = []
        self.synthesis_calls: list[dict[str, object]] = []

    def plan_query(self, *, question, history, context, tools, intents, model="planner"):
        self.plan_calls.append({"question": question, "context": context, "model": model})
        if self.plan_error is not None:
            raise self.plan_error
        return self.plan

    def synthesize_answer(self, *, question, intent, sources, catalog, model="synth"):
        self.synthesis_calls.append({"intent": intent, "sources": sources, "catalog": catalog, "model": model})
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


def _ask(session, provider, folder, scope, user, *, planned: PlannedFlow | None = None, limits=None):
    return AgentService(session, provider, limits or AgentLimits(), planned=planned).ask(
        scope=scope, user_id=user.id, question=QUESTION, providers=["google_drive"],
        mentions=[("folder", folder.id)], history=[],
    )


def _comparable(outcome):
    result, tool_results, references = outcome
    return (
        result.answer, result.retrieval_status, result.resolved_context,
        [(item.document_id, item.source_url) for item in result.citations], tool_results, references,
    )


def test_flag_off_never_plans_and_keeps_current_answer(semantic_session: Session) -> None:  # noqa: F811
    scope, user, folder, _document = _folder_with_files(semantic_session)
    baseline = _ask(semantic_session, FakeProvider({}), folder, scope, user)
    provider = PlanningProvider()

    default = _ask(semantic_session, provider, folder, scope, user)
    disabled = _ask(semantic_session, provider, folder, scope, user, planned=PlannedFlow(enabled=False))

    assert provider.plan_calls == [] and provider.synthesis_calls == []
    assert _comparable(default) == _comparable(baseline) == _comparable(disabled)
    assert "Síntese extrativa do conteúdo indexado" in baseline[0].answer


def test_flag_on_plans_runs_tools_and_synthesizes_with_sources(semantic_session: Session) -> None:  # noqa: F811
    scope, user, folder, document = _folder_with_files(semantic_session)
    provider = PlanningProvider()

    result, tool_results, references = _ask(
        semantic_session, provider, folder, scope, user,
        planned=PlannedFlow(enabled=True, planner_model="cheap", synthesis_model="final"),
    )

    assert [call["model"] for call in provider.plan_calls] == ["cheap"]
    assert provider.plan_calls[0]["context"]["mentioned_folders"] == 1
    [synthesis] = provider.synthesis_calls
    assert synthesis["model"] == "final"
    assert synthesis["intent"] == "inventory_with_summaries"
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
        "agent_flow": "planned", "intent": "inventory_with_summaries", "tools": ["list_library_children"],
    }
    assert [item["name"] for item in tool_results] == ["list_library_children"]
    assert {reference["name"] for reference in references} == {"Indexed.pdf", "Not indexed.pdf"}
    assert {reference["folder_id"] for reference in references} == {str(folder.id)}


@pytest.mark.parametrize(
    "provider",
    [
        PlanningProvider(plan_error=AIProviderUnavailable("AI provider deadline exceeded")),
        PlanningProvider(plan_error=ValueError("malformed planner JSON")),
        PlanningProvider(plan={"intent": "inventory", "tools": [{"name": "drop_tables", "query": ""}]}),
        PlanningProvider(plan={"intent": "unknown", "tools": []}),
        PlanningProvider(synthesis=GeneratedAnswer("", [])),
        PlanningProvider(synthesis=GeneratedAnswer("Insufficient evidence.", [])),
        PlanningProvider(synthesis=GeneratedAnswer("Resposta sem fonte.", [])),
        PlanningProvider(synthesis=GeneratedAnswer("Fonte inexistente [9].", [9])),
    ],
    ids=[
        "planner-timeout", "planner-invalid-json", "unknown-tool", "invalid-intent", "empty-synthesis",
        "insufficient-synthesis", "uncited-synthesis", "out-of-range-citation",
    ],
)
def test_planned_failures_fall_back_to_current_path(
    semantic_session: Session, provider: PlanningProvider,  # noqa: F811
) -> None:
    scope, user, folder, _document = _folder_with_files(semantic_session)
    baseline = _ask(semantic_session, FakeProvider({}), folder, scope, user)

    fallback = _ask(semantic_session, provider, folder, scope, user, planned=PlannedFlow(enabled=True))

    assert len(provider.plan_calls) == 1
    assert _comparable(fallback) == _comparable(baseline)


def test_planned_budget_timeout_falls_back_with_remaining_deadline(
    semantic_session: Session,  # noqa: F811
) -> None:
    scope, user, folder, _document = _folder_with_files(semantic_session)
    baseline = _ask(semantic_session, FakeProvider({}), folder, scope, user)
    provider = PlanningProvider()

    fallback = _ask(
        semantic_session, provider, folder, scope, user,
        planned=PlannedFlow(enabled=True, budget_fraction=0.0),
    )

    assert provider.synthesis_calls == []
    assert _comparable(fallback) == _comparable(baseline)


def test_planned_flow_ignores_providers_without_planning_adapter(
    semantic_session: Session,  # noqa: F811
) -> None:
    scope, user, folder, _document = _folder_with_files(semantic_session)
    baseline = _ask(semantic_session, FakeProvider({}), folder, scope, user)

    enabled = _ask(semantic_session, FakeProvider({}), folder, scope, user, planned=PlannedFlow(enabled=True))

    assert _comparable(enabled) == _comparable(baseline)


def test_planned_ordinal_follow_up_keeps_the_resolved_file_scope(
    semantic_session: Session,  # noqa: F811
) -> None:
    scope, user, folder, _document = _folder_with_files(semantic_session)
    listing = "Quais arquivos temos nessa pasta?"
    inventory, _tool_results, references = AgentService(semantic_session, FakeProvider({}), AgentLimits()).ask(
        scope=scope, user_id=user.id, question=listing, providers=["google_drive"],
        mentions=[("folder", folder.id)], history=[],
    )
    conversation, _ = ConversationService(semantic_session).create_or_load(
        scope=scope, user_id=user.id, conversation_id=None, question=listing,
    )
    ConversationService(semantic_session).append(
        conversation=conversation, role="assistant", content=inventory.answer or "",
        context={"references": references},
    )
    semantic_session.commit()
    _conversation, history = ConversationService(semantic_session).history(
        scope=scope, user_id=user.id, conversation_id=conversation.id,
    )
    provider = PlanningProvider(plan={"intent": "summary", "tools": [{"name": "summarize_previous_files", "query": ""}]})
    provider.vectors = {"Resuma o primeiro": [1.0, 0.0]}

    AgentService(semantic_session, provider, AgentLimits(), planned=PlannedFlow(enabled=True)).ask(
        scope=scope, user_id=user.id, question="Resuma o primeiro", providers=["google_drive"],
        mentions=[], history=history,
    )

    # The ordinal resolved one file: the planner sees it and cannot summarize every listed file.
    [plan_call] = provider.plan_calls
    assert plan_call["context"]["mentioned_files"] == 1
    assert plan_call["context"]["previous_answer_listed_files"] == 0
    assert provider.synthesis_calls == []


def test_plan_parsing_filters_tools_and_bounds_steps() -> None:
    plan = _parse_plan(
        {
            "intent": "question",
            "tools": [
                {"name": "search_library", "query": "  contrato  "},
                {"name": "search_library", "query": "contrato"},
                {"name": "unknown", "query": ""},
                {"name": "retrieve_evidence", "query": ""},
                {"name": "summarize_documents", "query": ""},
            ],
        },
        max_steps=2,
    )
    assert plan.intent == "question"
    assert plan.steps == (PlannedStep("search_library", "contrato"), PlannedStep("retrieve_evidence", ""))
    with pytest.raises(PlannedFlowRejected):
        _parse_plan({"intent": "question", "tools": [{"name": "unknown", "query": ""}]}, max_steps=2)
    with pytest.raises(PlannedFlowRejected):
        _parse_plan(["not", "a", "plan"], max_steps=2)


def test_authorization_errors_are_not_swallowed_by_fallback(semantic_session: Session) -> None:  # noqa: F811
    scope, user, folder, _document = _folder_with_files(semantic_session)
    provider = PlanningProvider(plan_error=SyncAccessDenied("folder unavailable"))

    with pytest.raises(SyncAccessDenied):
        _ask(semantic_session, provider, folder, scope, user, planned=PlannedFlow(enabled=True))


def test_eval_harness_compares_flag_off_and_on(semantic_session: Session, tmp_path) -> None:  # noqa: F811
    scope, user, folder, _document = _folder_with_files(semantic_session)
    cases_file = tmp_path / "cases.json"
    cases_file.write_text(json.dumps([
        {
            "id": "inventory-with-summaries", "question": QUESTION, "providers": ["google_drive"],
            "mentions": [{"kind": "folder", "node_id": "$FOLDER"}], "must_mention": ["Indexed.pdf"],
        },
    ]))
    cases = load_cases(cases_file, folder_id=folder.id)

    runs = compare(
        semantic_session, PlanningProvider(), cases, scope=scope, user_id=user.id,
        limits=AgentLimits(), planned=PlannedFlow(),
    )

    assert [(run.variant, run.flow, run.error) for run in runs] == [("off", "current", None), ("on", "planned", None)]
    assert all(run.citations == run.citations_with_link == 1 for run in runs)
    assert [run.answer_marks_sources for run in runs] == [False, True]
    assert [run.catalog_files_named for run in runs] == [2, 2]
    assert all(run.must_mention_hits == 1 and not run.answer_has_url for run in runs)
    report = markdown_report(runs)
    assert "Flag on: 1/1 answered by the planned flow" in report
    with pytest.raises(SystemExit):
        load_cases(cases_file, folder_id=None)


def test_planner_flag_is_off_by_default() -> None:
    settings = Settings(database_url="postgresql://user:secret@localhost/db")
    assert settings.agent_planner_enabled is False
    assert PlannedFlow().enabled is False


def _responses_envelope(payload: object) -> dict[str, object]:
    return {"output": [{"content": [{"type": "output_text", "text": json.dumps(payload)}]}]}


def test_openai_planner_and_synthesis_use_configured_models(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OpenAIQuestionProvider("key")
    bodies: list[dict[str, object]] = []
    replies = iter([
        _responses_envelope(INVENTORY_PLAN),
        _responses_envelope({"answer": "Resumo [1].", "citations": [1]}),
        {"output": [{"content": [{"type": "output_text", "text": "not json"}]}]},
    ])

    def fake_post(path, body):
        bodies.append(body)
        return next(replies)

    monkeypatch.setattr(provider, "_post", fake_post)
    plan = provider.plan_query(
        question=QUESTION, history=[], context={}, tools=["list_folder_inventory"], intents=["inventory"],
        model="cheap",
    )
    answer = provider.synthesize_answer(question=QUESTION, intent="inventory", sources=[], catalog=[], model="final")
    invalid = provider.synthesize_answer(question=QUESTION, intent="inventory", sources=[], catalog=[])

    assert plan == INVENTORY_PLAN
    assert answer == GeneratedAnswer("Resumo [1].", [1])
    assert invalid == GeneratedAnswer("", [])
    assert [body["model"] for body in bodies] == ["cheap", "final", "gpt-5-mini"]
    assert "URL" in bodies[1]["instructions"]
