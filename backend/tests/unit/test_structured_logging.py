import importlib
import logging

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.core.database import database_is_ready


class ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def make_application(monkeypatch) -> TestClient:
    """Build the app with a non-connecting PostgreSQL URL for middleware tests."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db")
    main = importlib.import_module("app.main")
    settings = Settings(database_url="postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db")
    return TestClient(main.create_app(settings))


def event_record(handler: ListHandler, event: str) -> logging.LogRecord:
    records = [record for record in handler.records if getattr(record, "event", None) == event]
    assert len(records) == 1
    return records[0]


def test_health_request_emits_structured_request_record(monkeypatch) -> None:
    client = make_application(monkeypatch)
    handler = ListHandler()
    request_logger = logging.getLogger("document_intelligence.request")
    request_logger.addHandler(handler)
    try:
        response = client.get("/health/live", headers={"x-request-id": "request-123"})
    finally:
        request_logger.removeHandler(handler)

    assert response.status_code == 200
    record = event_record(handler, "request_complete")
    assert record.request_id == "request-123"
    assert record.path == "/health/live"
    assert record.status == 200
    assert isinstance(record.elapsed_ms, float)
    assert record.elapsed_ms >= 0


def test_readiness_emits_structured_result_and_duration(monkeypatch) -> None:
    make_application(monkeypatch)
    handler = ListHandler()
    readiness_logger = logging.getLogger("document_intelligence.readiness")
    readiness_logger.addHandler(handler)
    try:
        assert database_is_ready(UnavailableEngine()) is False
    finally:
        readiness_logger.removeHandler(handler)

    record = event_record(handler, "readiness_check")
    assert record.result == "unavailable"
    assert isinstance(record.elapsed_ms, float)
    assert record.elapsed_ms >= 0


class UnavailableEngine:
    def connect(self):
        raise SQLAlchemyError("intentionally unavailable")
