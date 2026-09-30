import hashlib
from io import BytesIO

from pypdf import PdfReader, PdfWriter

from app.ingestion.blocks import ExtractedBlock
from app.ingestion.extraction import limits
from app.ingestion.extraction.errors import ExtractionError
from app.ingestion.extraction.ocr import OcrBudgetExceeded, OcrError


def _worth_ocr(total: int, low: int) -> bool:
    return low == total or low / total >= limits.OCR_MIN_LOW_PAGE_RATIO


def _subset(reader: PdfReader, indexes: list[int]) -> bytes:
    writer = PdfWriter()
    for index in indexes:
        writer.add_page(reader.pages[index])
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def pdf_blocks(content, *, ocr=None, budget=None):
    limits.guard_size(content)
    reader = PdfReader(BytesIO(content))
    if reader.is_encrypted and not reader.decrypt(""):
        raise ExtractionError("file_encrypted")
    texts = [page.extract_text() or "" for page in reader.pages]
    low = [i for i, text in enumerate(texts) if len(text.strip()) < limits.MIN_CHARS_PER_PAGE]
    recognized_indexes = set()
    if ocr is not None and low and _worth_ocr(len(texts), len(low)):
        if len(low) > limits.OCR_MAX_PAGES_PER_DOCUMENT:
            raise ExtractionError("ocr_document_too_large")
        try:
            if budget is not None:
                budget.reserve(len(low))
            key = f"{hashlib.sha256(content).hexdigest()}:{','.join(str(i) for i in low)}"
            recognized = ocr.recognize(_subset(reader, low), page_count=len(low), cache_key=key)
        except OcrBudgetExceeded:
            raise ExtractionError("ocr_budget_exceeded") from None
        except OcrError:
            raise ExtractionError("ocr_failed") from None
        if len(recognized) != len(low):
            raise ExtractionError("ocr_failed")
        recognized_indexes = set(low)
        for index, text in zip(low, recognized, strict=True):
            texts[index] = text
    return [ExtractedBlock(text, page_number=number, ocr=number - 1 in recognized_indexes) for number, text in enumerate(texts, start=1)]