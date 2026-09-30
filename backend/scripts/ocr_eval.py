"""PT-BR OCR evaluation: CER, WER, accent recall, optional live engine run.

Usage: python -m scripts.ocr_eval --engine docling_serve --url http://host:5001 \
    --corpus tests/fixtures/ocr_pt --report scripts/reports/ocr-eval-<date>.json
"""

import argparse
import json
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

THRESHOLDS = {"cer_clean": 0.03, "cer_degraded": 0.08, "accent_recall": 0.97}
CLEAN, DEGRADED = {"01", "05", "10"}, {"02", "03", "04", "08"}


def _edit_distance(a, b) -> int:
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def cer(reference: str, hypothesis: str) -> float:
    return _edit_distance(reference, hypothesis) / max(1, len(reference))


def wer(reference: str, hypothesis: str) -> float:
    ref, hyp = reference.split(), hypothesis.split()
    return _edit_distance(ref, hyp) / max(1, len(ref))


def _accents(word: str) -> Counter:
    return Counter(c for c in word if c.isalpha() and unicodedata.normalize("NFD", c) != c)


def accent_recall(reference: str, hypothesis: str) -> float:
    """Share of accented characters (incl. ç) of the reference kept in the aligned hypothesis words."""
    ref, hyp = reference.split(), hypothesis.split()
    total = kept = 0
    for tag, i1, i2, j1, j2 in SequenceMatcher(a=ref, b=hyp, autojunk=False).get_opcodes():
        for offset, word in enumerate(ref[i1:i2]):
            wanted = _accents(word)
            total += sum(wanted.values())
            if tag == "equal":
                kept += sum(wanted.values())
            elif tag == "replace" and j1 + offset < j2:
                kept += sum((wanted & _accents(hyp[j1 + offset])).values())
    return 1.0 if total == 0 else kept / total


def evaluate(engine, corpus: Path) -> dict:
    documents = {}
    for truth in sorted((corpus / "truth").glob("*.txt")):
        pdf = corpus / "pdf" / (truth.stem + ".pdf")
        reference = truth.read_text(encoding="utf-8")
        pages = engine.recognize(pdf.read_bytes(), page_count=1 + reference.count("\f"))
        hypothesis = "\f".join(pages) if "\f" in reference else "\n".join(pages)
        documents[truth.stem] = {
            "cer": cer(reference, hypothesis),
            "wer": wer(reference, hypothesis),
            "accent_recall": accent_recall(reference, hypothesis),
        }
    return {"documents": documents, "thresholds": THRESHOLDS}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=["docling_serve"], required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--corpus", type=Path, default=Path("tests/fixtures/ocr_pt"))
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    from app.ingestion.extraction.engines.docling_serve import DoclingServeEngine

    result = evaluate(DoclingServeEngine(args.url), args.corpus)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
