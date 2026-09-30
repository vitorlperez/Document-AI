from io import BytesIO

from pypdf import PdfReader

from app.ingestion.blocks import ExtractedBlock
from app.ingestion.extraction.errors import ExtractionError


def pdf_blocks(content: bytes, *, ocr=None, budget=None) -> list[ExtractedBlock]:
    reader = PdfReader(BytesIO(content))
    if reader.is_encrypted and not reader.decrypt(""):
        raise ExtractionError("file_encrypted")
    return [
        ExtractedBlock(page.extract_text() or "", page_number=index)
        for index, page in enumerate(reader.pages, start=1)
    ]
