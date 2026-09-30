from io import BytesIO

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.ingestion.extraction import extract_blocks, limits
from app.ingestion.extraction.errors import ExtractionError
from app.ingestion.extraction.ocr import OcrBudget, OcrBudgetExceeded

PDF = "application/pdf"


def pdf(pages: list[str | None]) -> bytes:
    """Text pages carry a real text layer; None = a blank page (what a scan looks like to pypdf)."""
    writer = PdfWriter()
    for text in pages:
        page = writer.add_blank_page(width=300, height=200)
        if text is not None:
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                                     NameObject("/BaseFont"): NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode())
            page[NameObject("/Contents")] = writer._add_object(stream)
    out = BytesIO(); writer.write(out); return out.getvalue()


class FakeOcr:
    name, version = "fake", "1"

    def __init__(self) -> None:
        self.calls: list[int] = []

    def recognize(self, pdf: bytes, *, page_count: int, cache_key: str | None = None) -> list[str]:
        self.calls.append(page_count)
        return [f"texto reconhecido {i}" for i in range(1, page_count + 1)]


TEXT = "Contrato de prestacao de servicos numero 42"


def test_text_pdf_never_calls_ocr() -> None:
    ocr = FakeOcr()
    blocks = extract_blocks(PDF, pdf([TEXT, TEXT]), ocr=ocr)
    assert [b.page_number for b in blocks] == [1, 2] and ocr.calls == []


def test_fully_scanned_pdf_is_recognized_page_by_page() -> None:
    ocr = FakeOcr()
    blocks = extract_blocks(PDF, pdf([None, None, None]), ocr=ocr)
    assert ocr.calls == [3]
    assert [(b.page_number, b.text) for b in blocks] == [(1, "texto reconhecido 1"), (2, "texto reconhecido 2"), (3, "texto reconhecido 3")]


def test_mixed_pdf_ocrs_only_the_empty_pages_and_keeps_page_numbers() -> None:
    ocr = FakeOcr()
    blocks = extract_blocks(PDF, pdf([TEXT, None, TEXT, None]), ocr=ocr)  # 50 % empty >= 30 %
    assert ocr.calls == [2]
    assert [b.text for b in blocks] == [TEXT, "texto reconhecido 1", TEXT, "texto reconhecido 2"]


def test_a_single_empty_page_in_a_long_text_pdf_is_not_worth_ocr() -> None:
    ocr = FakeOcr()
    extract_blocks(PDF, pdf([TEXT] * 9 + [None]), ocr=ocr)  # 10 % < 30 %
    assert ocr.calls == []


def test_without_an_engine_a_scanned_pdf_stays_empty_like_today() -> None:
    assert all(not b.text.strip() for b in extract_blocks(PDF, pdf([None, None])))


def test_budget_exhaustion_is_a_document_level_code() -> None:
    with pytest.raises(ExtractionError) as caught:
        extract_blocks(PDF, pdf([None] * 3), ocr=FakeOcr(), budget=OcrBudget(pages=2))
    assert caught.value.code == "ocr_budget_exceeded"


def test_deadline_counts_as_budget() -> None:
    now = [0.0]
    budget = OcrBudget(pages=100, deadline_seconds=10, monotonic=lambda: now[0])
    budget.reserve(1)
    now[0] = 11.0
    with pytest.raises(OcrBudgetExceeded):
        budget.reserve(1)


def test_document_with_too_many_scanned_pages_is_refused_with_a_code(monkeypatch) -> None:
    monkeypatch.setattr(limits, "OCR_MAX_PAGES_PER_DOCUMENT", 60)
    with pytest.raises(ExtractionError) as caught:
        extract_blocks(PDF, pdf([None] * 61), ocr=FakeOcr())
    assert caught.value.code == "ocr_document_too_large"


def test_ocr_page_cap_defaults_to_120_and_comes_from_env(monkeypatch) -> None:
    assert limits.OCR_MAX_PAGES_PER_DOCUMENT == 120
    monkeypatch.setenv("OCR_MAX_PAGES_PER_DOCUMENT", "7")
    assert limits.env_int("OCR_MAX_PAGES_PER_DOCUMENT", 120) == 7


def test_scanned_pages_are_recognized_in_batches_of_8_with_per_batch_cache_keys() -> None:
    class Spy(FakeOcr):
        keys: list = []

        def recognize(self, pdf, *, page_count, cache_key=None):
            self.keys.append(cache_key)
            return super().recognize(pdf, page_count=page_count, cache_key=cache_key)

    ocr = Spy()
    blocks = extract_blocks(PDF, pdf([None] * 19), ocr=ocr)
    assert ocr.calls == [8, 8, 3] and len(set(ocr.keys)) == 3
    assert [b.page_number for b in blocks] == list(range(1, 20)) and all(b.ocr for b in blocks)
    assert blocks[8].text == "texto reconhecido 1"  # second batch restarts its own numbering


def test_deadline_is_checked_between_batches() -> None:
    now = [0.0]
    budget = OcrBudget(pages=100, deadline_seconds=10, monotonic=lambda: now[0])

    class Slow(FakeOcr):
        def recognize(self, pdf, *, page_count, cache_key=None):
            now[0] += 11
            return super().recognize(pdf, page_count=page_count, cache_key=cache_key)

    ocr = Slow()
    with pytest.raises(ExtractionError) as caught:
        extract_blocks(PDF, pdf([None] * 10), ocr=ocr, budget=budget)
    assert caught.value.code == "ocr_budget_exceeded" and ocr.calls == [8]