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
