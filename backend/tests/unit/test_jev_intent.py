"""Jev as the intent engine (AGENT_INTENT_ENGINE=jev): typed decisions mapped onto the closed intent schema."""

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.knowledge import jev
from app.knowledge.agent import AgentLimits, AgentService, agent_service_from_settings
from app.knowledge.intent import parse_intent
from app.knowledge.jev import JevIntentClassifier, contextual_query, file_name_query
from app.knowledge.questions import AIProviderUnavailable
from tests.unit.test_agent_flow import IntentProvider, _intent, _profile_library
from tests.unit.test_semantic_questions import session as semantic_session  # noqa: F401

DATABASE_URL = "postgresql://user:password@localhost:5432/db"
HISTORY = [
    {"role": "user", "content": "Onde o Vitor trabalhou de 2023 a 2025?"},
    {"role": "assistant", "content": "Na Estoca, como Software Engineer [1]."},
]


def _answers(intent: str, target: str, **nouls: float) -> dict:
    answers = {
        "intent": {"type": "choice", "choice": intent, "confidence": 0.9, "probabilities": {intent: 0.9}},
        "target": {"type": "choice", "choice": target, "confidence": 0.9, "probabilities": {target: 0.9}},
    }
    answers.update({key: {"type": "noul", "noul": value} for key, value in nouls.items()})
    return {"answers": answers}


def _classifier(monkeypatch: pytest.MonkeyPatch, payload: dict, sent: list | None = None) -> JevIntentClassifier:
    def fake_post(url, *, headers, json, timeout):
        if sent is not None:
            sent.append(json)
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(jev.httpx, "post", fake_post)
    return JevIntentClassifier("sk-or-test")


def _context(**overrides) -> dict:
    return {"mentioned_folders": 0, "mentioned_files": 0, "previous_answer_listed_files": [],
            "previous_turn_had_files": False, "has_previous_answer": False, **overrides}


def test_choices_map_to_the_closed_schema_and_pass_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list = []
    classifier = _classifier(monkeypatch, _answers("summarize_files", "mentioned"), sent)

    raw = classifier.classify_intent(question="Resuma esse arquivo", history=[], context=_context(mentioned_files=1))
    decision = parse_intent(raw, listed_files=0, mentioned=1)

    assert (decision.intent, decision.target, decision.tool) == ("summarize_files", "mentioned", "summarize_documents")
    assert sent[0]["model"] == "jev-1.13"
    assert sent[0]["questions"]["intent"]["criteria"].keys() == set(jev.INTENT_CRITERIA)


def test_ordinals_come_from_one_yes_no_question_per_listed_file(monkeypatch: pytest.MonkeyPatch) -> None:
    listed = ["Contrato.pdf", "Proposta.docx", "Ata.pdf"]
    classifier = _classifier(
        monkeypatch, _answers("summarize_files", "previous_ordinals", ordinal_1=0.9, ordinal_2=0.1, ordinal_3=0.8),
    )

    raw = classifier.classify_intent(
        question="me explica o primeiro e o terceiro", history=[], context=_context(previous_answer_listed_files=listed),
    )

    assert parse_intent(raw, listed_files=3).ordinals == (1, 3)


def test_ordinal_target_without_a_confident_file_takes_the_most_likely(monkeypatch: pytest.MonkeyPatch) -> None:
    classifier = _classifier(
        monkeypatch, _answers("summarize_files", "previous_ordinals", ordinal_1=0.2, ordinal_2=0.4),
    )

    raw = classifier.classify_intent(
        question="resume esse", history=[], context=_context(previous_answer_listed_files=["A.pdf", "B.pdf"]),
    )

    assert raw["ordinals"] == [2]


def test_follow_up_fact_question_joins_the_conversation(monkeypatch: pytest.MonkeyPatch) -> None:
    classifier = _classifier(monkeypatch, _answers("ask_content", "previous_turn_files", needs_history=0.9))

    raw = classifier.classify_intent(question="quanto tempo ele ficou lá?", history=HISTORY, context=_context())

    assert raw["standalone_query"] == (
        "quanto tempo ele ficou lá? (contexto da conversa: Onde o Vitor trabalhou de 2023 a 2025? — "
        "Na Estoca, como Software Engineer.)"
    )


def test_self_contained_question_keeps_the_message(monkeypatch: pytest.MonkeyPatch) -> None:
    classifier = _classifier(monkeypatch, _answers("ask_content", "library", needs_history=0.1))

    raw = classifier.classify_intent(question="Qual a política de férias?", history=HISTORY, context=_context())

    assert raw["standalone_query"] == ""


def test_name_search_uses_the_name_written_after_the_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    classifier = _classifier(monkeypatch, _answers("list_files", "library", name_search=0.95))

    raw = classifier.classify_intent(
        question="Tem algum arquivo chamado orçamento 2026?", history=[], context=_context(),
    )

    assert (raw["tool"], raw["query"]) == ("search_library", "orçamento 2026")


@pytest.mark.parametrize(("message", "query"), [
    ("existe algum arquivo com nome nota fiscal março?", "nota fiscal março"),
    ("Is there a file called budget 2026?", "budget 2026"),
    ('tem um documento com o nome "Ata final"?', "Ata final"),
    ("acha pra mim o arquivo do contrato da Acme", ""),
])
def test_file_name_query(message: str, query: str) -> None:
    assert file_name_query(message) == query


def test_contextual_query_stays_within_the_question_limit() -> None:
    history = [{"role": "user", "content": "pergunta " * 50}, {"role": "assistant", "content": "resposta " * 200}]

    joined = contextual_query("e o prazo?", history)

    assert len(joined) <= jev.MAX_STANDALONE_CHARS and joined.startswith("e o prazo? (contexto da conversa:")


def test_provider_failure_is_reported_as_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_post(url, **kwargs):
        raise httpx.ConnectTimeout("timeout")

    monkeypatch.setattr(jev.httpx, "post", failing_post)

    with pytest.raises(AIProviderUnavailable):
        JevIntentClassifier("sk-or-test").classify_intent(question="oi", history=[], context=_context())


def test_jev_engine_requires_the_openrouter_key() -> None:
    with pytest.raises(ValidationError, match="OPENROUTER_API_KEY"):
        Settings(_env_file=None, database_url=DATABASE_URL, agent_intent_engine="jev", openrouter_api_key=None)


def test_settings_select_the_intent_engine(semantic_session: Session) -> None:  # noqa: F811
    default = agent_service_from_settings(
        semantic_session, IntentProvider(), Settings(_env_file=None, database_url=DATABASE_URL),
    )
    with_jev = agent_service_from_settings(
        semantic_session, IntentProvider(),
        Settings(_env_file=None, database_url=DATABASE_URL, agent_intent_engine="jev", openrouter_api_key="sk-or-x"),
    )

    assert default.intent_classifier is None
    assert isinstance(with_jev.intent_classifier, JevIntentClassifier)


def test_injected_classifier_decides_instead_of_the_provider(semantic_session: Session) -> None:  # noqa: F811
    scope, user, _node, _document = _profile_library(semantic_session)
    provider = IntentProvider(intent=_intent("list_files"), vectors={"O que sabemos sobre o Vitor?": [0.0, 1.0]})

    class Decider:
        calls = 0

        def classify_intent(self, *, question, history, context, model=""):
            Decider.calls += 1
            return _intent("ask_content", target="library", tool="retrieve_evidence")

    _result, tools, _references = AgentService(
        semantic_session, provider, limits=AgentLimits(),
        intent_classifier=Decider(),
    ).ask(
        scope=scope, user_id=user.id, question="O que sabemos sobre o Vitor?", providers=["google_drive"],
        mentions=[], history=[],
    )

    assert Decider.calls == 1 and provider.intent_calls == []
    assert [tool["name"] for tool in tools] == ["retrieve_evidence"]
