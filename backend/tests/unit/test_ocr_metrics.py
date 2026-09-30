import json
from pathlib import Path

import pytest

from scripts.ocr_eval import accent_recall, cer, evaluate, wer

CORPUS = Path(__file__).parents[1] / "fixtures/ocr_pt"


def test_cer_wer():
    assert cer("ação", "acao") == 0.5  # ç→c and ã→a: 2 edits in 4 chars (the plan said 0.25)
    assert cer("abc", "abc") == 0.0
    assert wer("um dois três", "um dois") == pytest.approx(1 / 3)


def test_accent_recall():
    assert accent_recall("ação órgão", "acao orgao") == 0.0
    assert accent_recall("ação órgão", "ação orgao") == 0.5
    assert accent_recall("sem acento", "qualquer") == 1.0


def test_corpus_has_truth_and_questions_for_every_pdf():
    truths = {p.stem for p in (CORPUS / "truth").glob("*.txt")}
    assert truths and truths == {p.stem for p in (CORPUS / "pdf").glob("*.pdf")}
    questions = json.loads((CORPUS / "questions.json").read_text(encoding="utf-8"))
    assert questions and {q["expected_doc"] for q in questions} <= truths


def test_evaluate_with_a_perfect_engine_meets_thresholds():
    class Oracle:
        def recognize(self, pdf, *, page_count, cache_key=None):
            stem = next(p.stem for p in (CORPUS / "pdf").glob("*.pdf") if p.read_bytes() == pdf)
            return (CORPUS / "truth" / f"{stem}.txt").read_text(encoding="utf-8").split("\f")

    report = evaluate(Oracle(), CORPUS)
    assert all(d["cer"] == 0 and d["accent_recall"] == 1 for d in report["documents"].values())
