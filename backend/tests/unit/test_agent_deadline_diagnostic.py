"""Deterministic diagnosis of the agent's shared time budget (no network)."""

from uuid import uuid4

import httpx
import pytest

from app.core.scoping import OrganizationScope
from app.knowledge import agent, questions
from app.knowledge.agent import AgentLimits, AgentService
from app.knowledge.questions import AIProviderUnavailable, OpenAIQuestionProvider


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _ask(service: AgentService) -> None:
    service.ask(
        scope=OrganizationScope(uuid4()), user_id=uuid4(), question="What is documented?",
        providers=[], mentions=[], history=[],
    )


def test_explicit_agent_deadline_after_slow_model_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = FakeClock()
    monkeypatch.setattr(agent.time, "monotonic", clock.monotonic)

    class SlowClassifier:
        def classify_intent(self, *, question, history, context, model):
            # The classifier gets its own short deadline inside the agent's budget.
            assert questions._REQUEST_DEADLINE.get() == 104.0
            clock.advance(25.0)
            return {"intent": "ask_content", "target": "library", "ordinals": [], "tool": "retrieve_evidence",
                    "query": ""}

    with pytest.raises(AIProviderUnavailable, match="document agent deadline exceeded"):
        _ask(AgentService(None, SlowClassifier(), AgentLimits(max_seconds=25)))
    assert clock.now == 125.0
    assert questions._REQUEST_DEADLINE.get() is None


def test_fallback_http_timeout_uses_remaining_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = FakeClock()
    monkeypatch.setattr(agent.time, "monotonic", clock.monotonic)
    calls: list[tuple[str, float]] = []

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict[str, object]:
            return {"output": []}

    def fake_post(url, *, headers, json, timeout):
        assert headers["Authorization"] == "Bearer simulated"
        calls.append((url.rsplit("/", 1)[-1], timeout))
        if len(calls) == 1:
            clock.advance(12.0)
            return FakeResponse()  # no classifier output -> relevance-search fallback
        clock.advance(timeout)
        raise httpx.ReadTimeout("simulated read timeout")

    monkeypatch.setattr(questions.httpx, "post", fake_post)
    provider = OpenAIQuestionProvider("simulated")
    service = AgentService(None, provider, AgentLimits(max_seconds=25))

    def fake_retrieve_evidence(**kwargs):
        provider._post("/v1/embeddings", {"model": "simulated", "input": ["synthetic"]})
        raise AssertionError("provider should time out")

    monkeypatch.setattr(service.tools, "retrieve_evidence", fake_retrieve_evidence)
    with pytest.raises(AIProviderUnavailable, match="AI provider is unavailable") as error:
        _ask(service)

    assert isinstance(error.value.__cause__, httpx.ReadTimeout)
    # The classifier is capped at its 4 s timeout; the fallback gets what is left of the 25 s budget.
    assert calls == [("responses", 4.0), ("embeddings", 13.0)]
    assert clock.now == 125.0
    assert questions._REQUEST_DEADLINE.get() is None


def test_provider_refuses_request_if_deadline_already_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = FakeClock()
    clock.advance(25.0)
    monkeypatch.setattr(questions.time, "monotonic", clock.monotonic)

    def unexpected_post(*args, **kwargs):
        raise AssertionError("no HTTP request should start after the deadline")

    monkeypatch.setattr(questions.httpx, "post", unexpected_post)
    with (
        questions.request_deadline(125.0),
        pytest.raises(AIProviderUnavailable, match="AI provider deadline exceeded") as error,
    ):
        OpenAIQuestionProvider("simulated")._post("/v1/responses", {})
    assert error.value.__cause__ is None
