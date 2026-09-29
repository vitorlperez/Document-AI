import json
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any


@dataclass
class RequestTrace:
    request_id: str
    provider_call_count: int = 0


_TRACE: ContextVar[RequestTrace | None] = ContextVar("request_trace", default=None)


@contextmanager
def request_context(request_id: str):
    token = _TRACE.set(RequestTrace(request_id))
    try:
        yield
    finally:
        _TRACE.reset(token)


def current_request_id() -> str | None:
    trace = _TRACE.get()
    return trace.request_id if trace else None


def provider_call_count(*, increment: bool = False) -> int:
    trace = _TRACE.get()
    if trace is None:
        return 0
    if increment:
        trace.provider_call_count += 1
    return trace.provider_call_count


_PHASES = frozenset({
    "planning", "tool_execution", "inventory", "retrieval_fallback", "finalization",
    "provider_http_responses", "provider_http_embeddings",
})
_FAILURES = frozenset({
    "agent_deadline", "provider_deadline_preflight", "read_timeout",
    "connect_timeout", "http_status", "network_error", "provider_unavailable",
    "internal_error",
})


def log_agent_phase(
    logger: logging.Logger, *, phase: str, started_at: float,
    deadline: float | None = None, failure_kind: str | None = None,
    status: int | None = None,
) -> None:
    if phase not in _PHASES or (failure_kind is not None and failure_kind not in _FAILURES):
        raise ValueError("invalid agent telemetry category")
    now = time.monotonic()
    logger.info(
        "agent phase complete",
        extra={
            "event": "agent_phase",
            "request_id": current_request_id(),
            "phase": phase,
            "elapsed_ms": round(max(0.0, now - started_at) * 1000, 2),
            "remaining_ms": round(max(0.0, deadline - now) * 1000, 2) if deadline is not None else None,
            "failure_kind": failure_kind,
            "status": status,
            "provider_call_count": provider_call_count(),
        },
    )


class JsonFormatter(logging.Formatter):
    """Serialize approved operational fields without logging request content or secrets."""

    fields = (
        "event",
        "request_id",
        "path",
        "status",
        "elapsed_ms",
        "result",
        "provider",
        "action",
        "job_id",
        "retrieval_status",
        "provider_outcome",
        "indexed_chunk_count",
        "compatible_embedding_count",
        "semantic_candidate_count",
        "lexical_candidate_count",
        "selected_candidate_count",
        "top_score_bucket",
        "phase",
        "remaining_ms",
        "failure_kind",
        "provider_call_count",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in self.fields:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def configure_observability() -> None:
    logger = logging.getLogger("document_intelligence")
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
