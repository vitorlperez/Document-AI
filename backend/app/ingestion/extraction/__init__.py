"""Bytes to located text blocks; one registry defines supported formats."""

import csv
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from docx.opc.exceptions import PackageNotFoundError
from lxml.etree import XMLSyntaxError
from openpyxl.utils.exceptions import InvalidFileException
from pptx.exc import PackageNotFoundError as PptxPackageNotFoundError
from pypdf.errors import PdfReadError

from app.ingestion.blocks import ExtractedBlock
from app.ingestion.extraction import docx, pdf, presentation, spreadsheet, text
from app.ingestion.extraction.errors import ExtractionError
from app.ingestion.extraction.limits import MAX_DOCUMENT_CHARS, guard_size, guard_zip
from app.ingestion.extraction.mime import (
    DOCX,
    GOOGLE_DOC,
    PDF,
    PPTX,
    SHEETS,
    SLIDES,
    XLSX,
    normalize_mime_type,
)
from app.knowledge.untrusted import strip_invisible

EXTRACTORS = {
    GOOGLE_DOC: text.google_doc_blocks,
    PDF: pdf.pdf_blocks,
    DOCX: docx.docx_blocks,
    "text/markdown": text.markdown_blocks_from_bytes,
    "text/plain": text.text_plain_blocks,
    "text/csv": spreadsheet.csv_blocks,
    XLSX: spreadsheet.xlsx_blocks,
    SHEETS: spreadsheet.xlsx_blocks,
    PPTX: presentation.pptx_blocks,
    SLIDES: presentation.pptx_blocks,
}
ELIGIBLE_MIME_TYPES = frozenset(EXTRACTORS)
BASE_MIME_TYPES = frozenset({GOOGLE_DOC, PDF, DOCX, "text/markdown"})


def eligible_mime_types(settings) -> frozenset[str]:
    return (
        ELIGIBLE_MIME_TYPES if getattr(settings, "new_formats_enabled", False) else BASE_MIME_TYPES
    )


def extract_blocks(
    mime_type: str, content: bytes, *, name: str = "", ocr=None, budget=None
) -> list[ExtractedBlock]:
    mime_type = normalize_mime_type(name, mime_type)
    extractor = EXTRACTORS.get(mime_type)
    if extractor is None:
        raise ValueError("unsupported file type")
    try:
        guard_size(content)
        if mime_type == DOCX:
            guard_zip(content)
        return sanitize_blocks(extractor(content, ocr=ocr, budget=budget) if mime_type == PDF else extractor(content))
    except ExtractionError:
        raise
    except (
        XMLSyntaxError,
        ParseError,
        PptxPackageNotFoundError,
        BadZipFile,
        PackageNotFoundError,
        PdfReadError,
        KeyError,
        csv.Error,
        InvalidFileException,
        UnicodeDecodeError,
        ValueError,
        OSError,
    ):
        raise ExtractionError("text_extraction_failed") from None


def sanitize_blocks(blocks: list[ExtractedBlock]) -> list[ExtractedBlock]:
    cleaned: list[ExtractedBlock] = []
    remaining = MAX_DOCUMENT_CHARS
    for block in blocks:
        text = strip_invisible(block.text.replace("\x00", ""))
        section = block.section_path.replace("\x00", "") if block.section_path else None
        if len(text) > remaining:
            if remaining:
                cleaned.append(ExtractedBlock(text[:remaining], block.page_number, section, block.ocr))
            cleaned.append(
                ExtractedBlock(
                    "[Conteúdo truncado: limite de texto do documento atingido.]",
                    block.page_number,
                    section,
                )
            )
            break
        cleaned.append(ExtractedBlock(text, block.page_number, section, block.ocr))
        remaining -= len(text)
    return cleaned
