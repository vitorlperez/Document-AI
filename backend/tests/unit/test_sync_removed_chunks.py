"""Invariant (e): removed documents keep no chunks or vectors."""
# ruff: noqa: F811  (pytest fixture imported from tests.sync_helpers)


from sqlalchemy import select
from sqlalchemy.orm import Session

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


# (e): chunks and vectors of removed documents are deleted.
def test_removed_documents_lose_chunks_and_vectors(session: Session) -> None:
    organization, user, source = seed(session)
    tda = space(session, organization, source, "tda", created_at=T0, folder_id="tda")
    sync(session, organization, user, tda, [doc("a"), doc("b")])
    b = session.scalar(select(Document).where(Document.external_file_id == "b"))
    assert session.scalars(select(DocumentChunk).where(DocumentChunk.document_id == b.id)).all()

    sync(session, organization, user, tda, [doc("a")], full_snapshot=True)
    assert b.index_status == "removed"
    assert session.scalars(select(DocumentChunk).where(DocumentChunk.document_id == b.id)).all() == []

    sync(session, organization, user, tda, [], full_snapshot=False)  # tombstone path
    session.execute(select(Document))
    assert session.scalars(select(DocumentChunk).join(Document).where(
        Document.index_status == "removed")).all() == []
