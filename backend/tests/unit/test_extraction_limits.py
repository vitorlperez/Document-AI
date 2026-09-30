from io import BytesIO
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from app.audit_usage.service import UsageLimitExceeded
from app.ingestion.blocks import ExtractedBlock
from app.ingestion.extraction import eligible_mime_types, extract_blocks, sanitize_blocks
from app.ingestion.extraction.errors import ExtractionError
from app.ingestion.extraction.limits import MAX_CHUNKS_PER_DOCUMENT, MAX_DOCUMENT_CHARS
from app.ingestion.service import DiscoveredDocument, IngestionService, _chunk_document


def test_text_cap_is_citable_and_preserves_location():
    blocks = extract_blocks("text/plain", b"x" * 1_000_000)
    assert sum(len(b.text) for b in blocks[:-1]) <= MAX_DOCUMENT_CHARS
    assert "Conteúdo truncado" in blocks[-1].text


def test_sanitize_removes_nul_from_text_and_sections():
    assert sanitize_blocks([ExtractedBlock("a\x00b", 3, "s\x00")]) == [ExtractedBlock("ab", 3, "s")]


def test_document_chunks_are_capped_with_final_notice():
    blocks = tuple(ExtractedBlock("body", i) for i in range(2500))
    chunks = _chunk_document(
        DiscoveredDocument("id", "name", "text/plain", "", text="body", blocks=blocks)
    )
    assert len(chunks) == MAX_CHUNKS_PER_DOCUMENT
    assert "Conteúdo truncado" in chunks[-1].text


def test_new_formats_flag_keeps_base_only_when_disabled():
    assert "text/csv" not in eligible_mime_types(SimpleNamespace(new_formats_enabled=False))
    assert "text/csv" in eligible_mime_types(SimpleNamespace(new_formats_enabled=True))


def test_zip_bomb_fails_before_decompression():
    out = BytesIO()
    with ZipFile(out, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("payload", b"0" * 1_000_000)
    with pytest.raises(ExtractionError) as error:
        extract_blocks(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", out.getvalue()
        )
    assert error.value.code == "file_too_large"


def test_active_document_limit_is_configurable():
    class Session:
        def __init__(self):
            self.results = iter([object(), 3])

        def scalar(self, statement):
            return next(self.results)

    service = IngestionService(
        Session(), settings=SimpleNamespace(active_document_limit=3, new_formats_enabled=True)
    )
    with pytest.raises(UsageLimitExceeded):
        service._require_active_document_capacity(organization_id="org")
