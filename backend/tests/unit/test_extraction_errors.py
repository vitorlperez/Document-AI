from io import BytesIO

import pytest
from pypdf import PdfWriter

from app.ingestion.extraction import extract_blocks
from app.ingestion.extraction.errors import ExtractionError


@pytest.mark.parametrize(
    "mime,content,code",
    [
        (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            b"PK\x03\x04garbage",
            "text_extraction_failed",
        ),
        ("application/pdf", b"broken PDF", "text_extraction_failed"),
        (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            b"broken deck",
            "text_extraction_failed",
        ),
    ],
)
def test_corrupt_files_have_safe_codes(mime, content, code):
    with pytest.raises(ExtractionError) as error:
        extract_blocks(mime, content)
    assert error.value.code == code


def test_password_protected_pdf_has_explicit_code():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("pw")
    out = BytesIO()
    writer.write(out)
    with pytest.raises(ExtractionError) as error:
        extract_blocks("application/pdf", out.getvalue())
    assert error.value.code == "file_encrypted"


def test_invalid_xml_inside_office_zip_has_safe_code():
    from zipfile import ZipFile

    from docx import Document

    doc = BytesIO()
    Document().save(doc)
    broken = BytesIO()
    with ZipFile(doc) as source, ZipFile(broken, "w") as target:
        for entry in source.infolist():
            target.writestr(
                entry,
                b"<document>" if entry.filename == "word/document.xml" else source.read(entry),
            )
    with pytest.raises(ExtractionError) as error:
        extract_blocks(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            broken.getvalue(),
        )
    assert error.value.code == "text_extraction_failed"
