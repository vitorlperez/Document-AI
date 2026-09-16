import json
import logging

from app.core.logging import JsonFormatter


def test_json_formatter_allows_safe_retrieval_metrics_without_serializing_content() -> None:
    record = logging.LogRecord(
        name="document_intelligence.questions",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="semantic question complete",
        args=(),
        exc_info=None,
    )
    record.event = "semantic_question"
    record.retrieval_status = "below_evidence_threshold"
    record.provider_outcome = "not_called"
    record.indexed_chunk_count = 12
    record.compatible_embedding_count = 12
    record.semantic_candidate_count = 12
    record.lexical_candidate_count = 2
    record.selected_candidate_count = 0
    record.top_score_bucket = "0_2_to_0_39"
    record.prompt = "PRIVATE_QUESTION"
    record.chunk_text = "PRIVATE_DOCUMENT_CONTENT"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["retrieval_status"] == "below_evidence_threshold"
    assert payload["top_score_bucket"] == "0_2_to_0_39"
    assert payload["selected_candidate_count"] == 0
    assert "PRIVATE_QUESTION" not in str(payload)
    assert "PRIVATE_DOCUMENT_CONTENT" not in str(payload)
