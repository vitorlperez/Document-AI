"""Sanitized, request-scoped telemetry for the document agent."""

import asyncio
import importlib
import json
import logging
import time
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.core.logging import JsonFormatter, current_request_id, request_context
from app.core.scoping import OrganizationScope
from app.knowledge import agent
from app.knowledge.agent import AgentLimits, AgentService
from app.knowledge.questions import (
    AIProviderUnavailable,
    OpenAIQuestionProvider,
    QuestionResult,
    QuestionService,
    request_deadline,
)


class Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.events.append(json.loads(JsonFormatter().format(record)))


def test_request_ids_are_isolated_between_overlapping_requests(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test_user:unused@localhost:5432/test_db")
    main = importlib.import_module("app.main")
    app = FastAPI()
    gate = asyncio.Event()
    arrivals = 0

    class FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {"output": []}

    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: FakeResponse())
    capture = Capture()
    request_logger = logging.getLogger("document_intelligence.request")
    question_logger = logging.getLogger("document_intelligence.questions")
    request_logger.addHandler(capture)
    question_logger.addHandler(capture)

    @app.get("/probe")
    async def probe():
        nonlocal arrivals
        arrivals += 1
        if arrivals == 2:
            gate.set()
        await gate.wait()
        await asyncio.sleep(0)
        OpenAIQuestionProvider("simulated")._post("/v1/responses", {"input": "PRIVATE_PROMPT"})
        QuestionService(None, None)._complete(
            QuestionResult(None, "insufficient_evidence", [], "no_indexed_content"),
            started_at=time.perf_counter(), indexed_chunk_count=0,
        )
        return {"request_id": current_request_id()}

    app.add_middleware(main.RequestLogMiddleware)

    async def run() -> list[httpx.Response]:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return list(await asyncio.gather(
                client.get("/probe", headers={"x-request-id": "first"}),
                client.get("/probe", headers={"x-request-id": "second"}),
            ))

    try:
        responses = asyncio.run(run())
    finally:
        request_logger.removeHandler(capture)
        question_logger.removeHandler(capture)
    assert [response.json()["request_id"] for response in responses] == ["first", "second"]
    for request_id in ("first", "second"):
        events = [item for item in capture.events if item.get("request_id") == request_id]
        assert {item["event"] for item in events} == {"request_complete", "agent_phase", "semantic_question"}
        assert next(item for item in events if item["event"] == "request_complete")["provider_call_count"] == 1
    assert "PRIVATE_PROMPT" not in json.dumps(capture.events)
    assert current_request_id() is None


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (httpx.ReadTimeout("PRIVATE_ERROR"), "read_timeout"),
        (httpx.ConnectTimeout("PRIVATE_ERROR"), "connect_timeout"),
        (httpx.ConnectError("PRIVATE_ERROR"), "network_error"),
        (httpx.HTTPStatusError("PRIVATE_ERROR", request=httpx.Request("POST", "https://secret.test/private"), response=httpx.Response(502)), "http_status"),
    ],
)
def test_provider_failure_categories_are_correlated_and_sanitized(monkeypatch, error, expected) -> None:
    def fake_post(*args, **kwargs):
        raise error

    monkeypatch.setattr(httpx, "post", fake_post)
    capture = Capture()
    logger = logging.getLogger("document_intelligence.questions")
    logger.addHandler(capture)
    try:
        with request_context("diagnostic-123"), pytest.raises(AIProviderUnavailable):
            OpenAIQuestionProvider("PRIVATE_TOKEN")._post("/v1/responses", {"input": "PRIVATE_PROMPT"})
    finally:
        logger.removeHandler(capture)

    event = next(item for item in capture.events if item.get("event") == "agent_phase")
    assert event["request_id"] == "diagnostic-123"
    assert event["phase"] == "provider_http_responses"
    assert event["failure_kind"] == expected
    assert event.get("status") == (502 if expected == "http_status" else None)
    assert event["provider_call_count"] == 1
    assert event["elapsed_ms"] >= 0
    serialized = json.dumps(event)
    for forbidden in ("PRIVATE_ERROR", "PRIVATE_TOKEN", "PRIVATE_PROMPT", "secret.test", "https://"):
        assert forbidden not in serialized


def test_request_context_restores_previous_trace() -> None:
    with request_context("outer"):
        with request_context("inner"):
            assert current_request_id() == "inner"
        assert current_request_id() == "outer"
    assert current_request_id() is None


def test_provider_preflight_logs_deadline_without_http(monkeypatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: pytest.fail("HTTP must not start"))
    capture = Capture()
    logger = logging.getLogger("document_intelligence.questions")
    logger.addHandler(capture)
    try:
        with (
            request_context("expired-123"), request_deadline(time.monotonic() - 1),
            pytest.raises(AIProviderUnavailable, match="deadline exceeded"),
        ):
            OpenAIQuestionProvider("simulated")._post("/v1/responses", {})
    finally:
        logger.removeHandler(capture)
    event = next(item for item in capture.events if item.get("event") == "agent_phase")
    assert event["failure_kind"] == "provider_deadline_preflight"
    assert event["remaining_ms"] == 0
    assert event["provider_call_count"] == 0


def test_agent_logs_elapsed_remaining_and_explicit_deadline(monkeypatch) -> None:
    clock = [100.0]
    monkeypatch.setattr(agent.time, "monotonic", lambda: clock[0])

    class SlowProvider:
        def tool_calls(self, *, question, history, tool_results):
            clock[0] += 25.0
            return []

    capture = Capture()
    logger = logging.getLogger("document_intelligence.agent")
    logger.addHandler(capture)
    try:
        with request_context("budget-123"), pytest.raises(AIProviderUnavailable):
            AgentService(None, SlowProvider(), AgentLimits(max_seconds=25)).ask(
                scope=OrganizationScope(uuid4()), user_id=uuid4(), question="synthetic",
                providers=[], mentions=[], history=[],
            )
    finally:
        logger.removeHandler(capture)

    phases = [item for item in capture.events if item.get("event") == "agent_phase"]
    assert [(item["phase"], item.get("failure_kind")) for item in phases] == [
        ("planning", None), ("retrieval_fallback", "agent_deadline"),
    ]
    assert phases[0]["elapsed_ms"] == 25000.0
    assert all(item["remaining_ms"] == 0 for item in phases)
    assert all(item["request_id"] == "budget-123" for item in phases)


def _middleware_client(monkeypatch, handler_raises: bool):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test_user:unused@localhost:5432/test_db")
    main = importlib.import_module("app.main")
    app = FastAPI()

    @app.get("/probe")
    async def probe():
        if handler_raises:
            raise RuntimeError("PRIVATE_ERROR")
        return {"request_id": current_request_id()}

    app.add_middleware(main.RequestLogMiddleware)
    return app


@pytest.mark.parametrize("hostile", ["x" * 500, "bad id\twith spaces", "a/b;c", "<script>"])
def test_hostile_client_request_id_is_replaced(monkeypatch, hostile) -> None:
    app = _middleware_client(monkeypatch, handler_raises=False)

    async def run() -> httpx.Response:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.get("/probe", headers={"x-request-id": hostile})

    response = asyncio.run(run())
    returned = response.headers["x-request-id"]
    assert returned != hostile
    assert response.json()["request_id"] == returned
    assert len(returned) <= 64


def test_middleware_logs_request_when_handler_raises(monkeypatch) -> None:
    app = _middleware_client(monkeypatch, handler_raises=True)
    capture = Capture()
    request_logger = logging.getLogger("document_intelligence.request")
    request_logger.addHandler(capture)

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
        ) as client:
            await client.get("/probe", headers={"x-request-id": "boom-1"})

    try:
        asyncio.run(run())
    finally:
        request_logger.removeHandler(capture)
    events = [item for item in capture.events if item.get("request_id") == "boom-1"]
    assert [item["event"] for item in events] == ["request_complete"]
    assert events[0]["status"] == 500
    assert "PRIVATE_ERROR" not in json.dumps(capture.events)
