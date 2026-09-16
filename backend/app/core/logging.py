import json
import logging
from typing import Any


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
