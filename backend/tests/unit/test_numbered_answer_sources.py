from uuid import uuid4

from app.api.ingestion import _answer_without_source_links
from app.knowledge.questions import Evidence, _number_answer_sources


def evidence(url: str, name: str = "Document") -> Evidence:
    return Evidence(uuid4(), name, uuid4(), "excerpt", None, url, 1.0)


def test_evidence_indexes_map_to_unique_display_documents() -> None:
    first = evidence("https://example.org/a/#fragment", "First")
    first_copy = evidence("https://example.org/a/", "Copy")
    second = evidence("https://example.org/b", "Second")
    selected = [first, first_copy, second]
    answer = _number_answer_sources(
        "Um fato [2][3], outro [1], sem apoio [9].",
        [2, 3, 1], selected, [first_copy, second, first],
    )
    assert answer == "Um fato (fontes 1 e 2), outro (fonte 1), sem apoio."
    assert _answer_without_source_links(answer) == answer


def test_uncited_valid_index_does_not_create_reference() -> None:
    first, second = evidence("https://example.org/a"), evidence("https://example.org/b")
    assert _number_answer_sources("Válido [2], omitido [1].", [2], [first, second], [second]) == (
        "Válido (fonte 1), omitido."
    )


def test_answer_without_model_markers_is_preserved() -> None:
    first = evidence("https://example.org/a")
    assert _number_answer_sources("Fato sem marcador.", [1], [first], [first]) == "Fato sem marcador."
