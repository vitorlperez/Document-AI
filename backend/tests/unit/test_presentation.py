import logging
from uuid import uuid4

from app.knowledge.presentation import (
    answer_without_source_links,
    serialize_question_result,
    strip_answer_links,
)
from app.knowledge.questions import Evidence, QuestionResult


def test_images_and_links(caplog):
    with caplog.at_level(logging.INFO):
        text, count = strip_answer_links(
            "veja ![x](https://evil.test/?q=(1)) e [aqui](https://a.test) https://b.test"
        )
    assert " ".join(text.split()) == "veja e aqui"
    assert count == 3
    assert "answer_links_stripped" in caplog.text
    assert "evil.test" not in caplog.text


def test_markers_and_filenames():
    text = "relatorio.v2.pdf [1][2]"
    assert strip_answer_links(text) == (text, 0)
    assert answer_without_source_links(None) is None


def test_serialization():
    item = Evidence(
        document_id=uuid4(),
        document_name="Plano.pdf",
        chunk_id=uuid4(),
        excerpt="x" * 500,
        page_number=2,
        source_url="https://drive.test/plano",
        score=1.0,
        source_provider="google_drive",
    )
    payload = serialize_question_result(
        QuestionResult(
            "Resposta [1] ![x](https://evil.test)", "supported", [item], "sufficient_evidence"
        ),
        include_provider=True,
    )
    assert "evil.test" not in payload["answer"] and "![" not in payload["answer"]
    citation = payload["citations"][0]
    assert citation["source_url"] == item.source_url
    assert len(citation["excerpt"]) <= 241 and citation["source_provider"] == "google_drive"


def test_service_results_are_safe_before_http_serialization():
    from app.knowledge.questions import GeneratedAnswer

    assert GeneratedAnswer("Resposta [1] ![x](https://evil.test)", [1]).text == "Resposta [1] "
    result = QuestionResult(
        "Veja [aqui](https://evil.test) [1]", "supported", [], "sufficient_evidence"
    )
    assert result.answer == "Veja aqui [1]"
