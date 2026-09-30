from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import select
from test_ingestion_embeddings import document, stage_sync, workspace
from test_ingestion_embeddings import session as session  # noqa: PLC0414 — pytest fixture discovery
from test_ingestion_scheduler import create_workspace, schedule
from test_ingestion_scheduler import (
    settings as settings,  # noqa: PLC0414 — pytest fixture discovery
)

from app.audit_usage.models import UsageRecord
from app.audit_usage.service import MONTHLY_LIMITS
from app.ingestion.blocks import ExtractedBlock
from app.knowledge.models import Document


def test_sync_debits_ocr_pages(session):
    org, user, folder = workspace(session)
    item = replace(document("ação no contrato"), blocks=(ExtractedBlock("ação no contrato", 1, ocr=True),))
    stage_sync(session, org, user, folder, [item])
    usage = session.scalar(select(UsageRecord).where(UsageRecord.metric=="ocr_pages"))
    assert usage.quantity == 1


def test_monthly_budget_fails_document_and_continues(session, monkeypatch):
    monkeypatch.setitem(MONTHLY_LIMITS, "ocr_pages", 0)
    org, user, folder = workspace(session)
    item = replace(document("ação no contrato"), blocks=(ExtractedBlock("ação no contrato", 1, ocr=True),))
    other = replace(document("normal text"), external_file_id="other")
    stage_sync(session, org, user, folder, [item, other])
    rows = {d.external_file_id:d for d in session.scalars(select(Document))}
    assert rows["briefing-1"].error_code == "ocr_budget_exceeded"
    assert rows["other"].index_status == "indexed"


def test_scheduler_retries_ocr_before_freshness(session, settings):
    now = datetime.now(UTC)
    _source, folder = create_workspace(session, last_synced_at=now)
    session.add(Document(organization_id=folder.organization_id,workspace_folder_id=folder.id,
        external_file_id="scan",name="scan.pdf",mime_type="application/pdf",source_url="https://example.test",
        index_status="failed",error_code="ocr_budget_exceeded",content_hash=""))
    session.commit()
    assert len(schedule(session, settings, now)) == 1
