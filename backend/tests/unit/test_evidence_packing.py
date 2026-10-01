"""Evidence packing re-merges only the candidate's document; the selection must match the full re-merge."""

import random
from uuid import uuid4

import pytest

from app.knowledge.questions import (
    MAX_EVIDENCE_CONTEXT_CHARS,
    Evidence,
    _evidence_context_chars,
    _merge_contiguous_evidence,
    _select_diverse_evidence,
)

WORDS = ["contrato", "prazo", "multa", "reajuste", "cliente", "proposta", "pagamento", "vigência", "cláusula", "entrega"]


def _reference_select(evidence: list[Evidence], *, max_chars: int | None = None) -> list[Evidence]:
    """The previous implementation: every candidate re-merges everything selected so far."""
    budget = MAX_EVIDENCE_CONTEXT_CHARS if max_chars is None else max_chars
    selected: list[Evidence] = []
    for item in sorted(evidence, key=lambda item: -item.score):
        proposed = _merge_contiguous_evidence([*selected, item])
        if sum(_evidence_context_chars(passage) for passage in proposed) <= budget:
            selected.append(item)
    document_order = {item.document_id: index for index, item in reversed(list(enumerate(evidence)))}
    selected.sort(key=lambda item: document_order[item.document_id])
    return _merge_contiguous_evidence(selected)


def _random_evidence(rng: random.Random) -> list[Evidence]:
    documents = [uuid4() for _ in range(rng.randint(1, 5))]
    texts: dict[tuple[int, int], str] = {}
    items: list[Evidence] = []
    for _ in range(rng.randint(1, 30)):
        document = rng.randrange(len(documents))
        position = rng.randint(0, 12)
        if (document, position) not in texts:
            body = " ".join(rng.choice(WORDS) for _ in range(rng.randint(5, 80)))
            previous = texts.get((document, position - 1))
            # Chunkers repeat the end of the previous chunk; exercise the overlap join.
            if previous and rng.random() < 0.5:
                body = " ".join(previous.split()[-rng.randint(3, 6):]) + " " + body
            texts[(document, position)] = body
        items.append(Evidence(
            documents[document], f"Doc {document}.pdf", uuid4(), texts[(document, position)], position + 1,
            "https://example.test/doc", rng.random(), chunk_ids=(uuid4(),), chunk_positions=(position,),
        ))
    return items


@pytest.mark.parametrize("seed", range(300))
def test_per_document_packing_matches_the_full_re_merge(seed: int) -> None:
    rng = random.Random(seed)
    evidence = _random_evidence(rng)
    budget = rng.choice([None, 300, 800, 2000, 5000])

    assert _select_diverse_evidence(evidence, max_chars=budget) == _reference_select(evidence, max_chars=budget)
