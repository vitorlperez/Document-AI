"""Invariant (d): manual resync rescans all but rebuilds only what changed."""
# ruff: noqa: F811  (pytest fixture imported from tests.sync_helpers)


from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.ingestion.service import DiscoveryResult, IngestionService
from app.knowledge.models import Document, DocumentChunk
from tests.sync_helpers import (  # noqa: F401
    T0,
    TREE,
    doc,
    exclude,
    seed,
    session,
    space,
    statuses,
    sync,
)


# (d): the manual resync rescans everything but only rebuilds what changed.
def test_manual_resync_rebuilds_only_changed_documents(session: Session) -> None:
    from app.library.manual_sync import request_run

    organization, user, source = seed(session)
    tda = space(session, organization, source, "tda", created_at=T0, folder_id="tda")
    sync(session, organization, user, tda, [doc("a"), doc("b")])
    before = {chunk.document_id: chunk.id for chunk in session.scalars(select(DocumentChunk))}
    run, jobs = request_run(session, scope=OrganizationScope(organization.id), user=user,
                            workspace_id=tda.id)
    service = IngestionService(session)
    job = service.claim(job_id=jobs[0].id)
    service.apply_reconciliation(
        job_id=job.id, run_token=job.run_token,
        documents=DiscoveryResult(documents=[doc("a"), doc("b", text="mudou")], full_snapshot=True),
        manual_folders=TREE,
    )
    after = {chunk.document_id: chunk.id for chunk in session.scalars(select(DocumentChunk))}
    a = session.scalar(select(Document).where(Document.external_file_id == "a"))
    b = session.scalar(select(Document).where(Document.external_file_id == "b"))
    assert after[a.id] == before[a.id]
    assert after[b.id] != before[b.id]
    assert run.progress[str(job.id)]["processed"] == 2


def test_manual_resync_reprocess_all_rebuilds_every_document(session: Session) -> None:
    from app.library.manual_sync import request_run

    organization, user, source = seed(session)
    tda = space(session, organization, source, "tda", created_at=T0, folder_id="tda")
    sync(session, organization, user, tda, [doc("a")])
    before = session.scalar(select(DocumentChunk.id))
    _run, jobs = request_run(session, scope=OrganizationScope(organization.id), user=user,
                             workspace_id=tda.id, reprocess_all=True)
    service = IngestionService(session)
    job = service.claim(job_id=jobs[0].id)
    service.apply_reconciliation(job_id=job.id, run_token=job.run_token,
                                 documents=DiscoveryResult(documents=[doc("a")], full_snapshot=True),
                                 manual_folders=TREE)
    assert session.scalar(select(DocumentChunk.id)) != before
