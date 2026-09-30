from app.ingestion.extraction import ELIGIBLE_MIME_TYPES, extract_blocks
from app.ingestion.service import ELIGIBLE_MIME_TYPES as SERVICE_ELIGIBLE
from app.ingestion.service import ExtractedBlock

BASE = {
    "application/vnd.google-apps.document",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/markdown",
}


def test_registry_is_the_single_source_of_eligibility() -> None:
    assert SERVICE_ELIGIBLE is ELIGIBLE_MIME_TYPES
    assert BASE <= ELIGIBLE_MIME_TYPES


def test_markdown_keeps_heading_paths_after_the_move() -> None:
    blocks = extract_blocks("text/markdown", b"# A\n\ntexto\n\n## B\n\nmais")
    assert blocks == [
        ExtractedBlock("texto", section_path="A"),
        ExtractedBlock("mais", section_path="A › B"),
    ]
