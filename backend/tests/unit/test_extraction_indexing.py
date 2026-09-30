from io import BytesIO
from types import SimpleNamespace

import pytest
from openpyxl import Workbook
from sqlalchemy import select
from test_extraction_presentation import deck
from test_ingestion_service import create_workspace
from test_ingestion_service import session as session  # noqa: PLC0414 -- pytest fixture re-export

from app.core.scoping import OrganizationScope
from app.ingestion.extraction import extract_blocks
from app.ingestion.extraction.mime import PPTX, SHEETS, SLIDES, XLSX
from app.ingestion.service import DiscoveredDocument, IngestionService
from app.knowledge.models import Document, DocumentChunk


def content_for(mime):
    if mime in {PPTX, SLIDES}:
        return deck()
    if mime in {XLSX, SHEETS}:
        wb = Workbook()
        wb.active.title = "Contratos"
        wb.active.append(["Cliente", "Valor"])
        wb.active.append(["Acme", 1500])
        out = BytesIO()
        wb.save(out)
        return out.getvalue()
    return b"Cliente;Valor\nAcme;1500" if mime == "text/csv" else b"Prazo de 30 dias"


@pytest.mark.parametrize("mime", ["text/plain", "text/csv", XLSX, PPTX, SHEETS, SLIDES])
def test_new_format_fixture_indexes_with_citable_chunks(session, mime):
    org, admin, folder = create_workspace(session)
    service = IngestionService(
        session, settings=SimpleNamespace(new_formats_enabled=True, active_document_limit=500)
    )
    job = service.enqueue(
        scope=OrganizationScope(org.id), user_id=admin.id, workspace_folder_id=folder.id
    )
    blocks = extract_blocks(mime, content_for(mime))
    service.reconcile(
        job_id=job.id,
        documents=[
            DiscoveredDocument(
                "new",
                "Fixture",
                mime,
                "https://example.test/file",
                text="\n\n".join(b.text for b in blocks),
                blocks=tuple(blocks),
            )
        ],
    )
    doc = session.scalar(select(Document))
    assert doc.index_status == "indexed"
    chunks = list(session.scalars(select(DocumentChunk).where(DocumentChunk.document_id == doc.id)))
    assert chunks and all(chunk.text.strip() for chunk in chunks)
    if mime in {XLSX, SHEETS, "text/csv"}:
        assert "Cliente: Acme | Valor: 1500" in chunks[0].text
        assert "linhas 2–2" in chunks[0].search_text
    if mime in {PPTX, SLIDES}:
        assert chunks[0].page_number == 1
        assert "Proposta comercial" in chunks[0].search_text
