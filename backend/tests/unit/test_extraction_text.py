from app.ingestion.extraction.mime import normalize_mime_type
from app.ingestion.extraction.text import decode_text, text_plain_blocks

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_extension_wins_over_generic_types_only() -> None:
    assert normalize_mime_type("notas.md", "application/octet-stream") == "text/markdown"
    assert normalize_mime_type("base.CSV", "text/plain") == "text/csv"
    assert normalize_mime_type("plano.xlsx", "") == XLSX
    assert (
        normalize_mime_type("contrato.pdf", "application/pdf") == "application/pdf"
    )  # specific type is kept
    assert normalize_mime_type("foto.jpg", "application/octet-stream") == "application/octet-stream"


def test_decode_text_handles_bom_utf16_and_windows_1252() -> None:
    assert decode_text("ação".encode("utf-8-sig")) == "ação"
    assert decode_text("ação".encode("utf-16")) == "ação"
    assert decode_text("ação".encode("cp1252")) == "ação"


def test_plain_text_becomes_paragraph_blocks() -> None:
    blocks = text_plain_blocks("Primeiro parágrafo.\nContinua.\n\nSegundo.".encode())
    assert [b.text for b in blocks] == ["Primeiro parágrafo.\nContinua.", "Segundo."]
