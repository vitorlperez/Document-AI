"""C1/C3: canonical-document lookup uses EXISTS (no DISTINCT over chunk joins); big folder lists go through ids_clause."""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.models import Base
from app.knowledge.models import Document, DocumentChunk
from app.knowledge.questions import EMBEDDING_MODEL, QuestionService
from tests.spaces_helpers import seed_world


def _session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_canonical_document_ids_uses_exists_not_distinct_join():
    session = _session()
    world = seed_world(session)
    statements: list[str] = []
    event.listen(session.get_bind(), "before_cursor_execute",
                 lambda conn, cur, statement, *rest: statements.append(statement))
    folder_ids = list(world.folders.values())
    filters = [
        Document.organization_id == world.organization_id, Document.workspace_folder_id.in_(folder_ids),
        Document.index_status == "indexed", DocumentChunk.organization_id == world.organization_id,
        DocumentChunk.workspace_folder_id.in_(folder_ids), DocumentChunk.workspace_folder_id == Document.workspace_folder_id,
        DocumentChunk.embedding.is_not(None), DocumentChunk.embedding_model == EMBEDDING_MODEL,
    ]
    metadata = {folder_id: (world.source_id, "google_drive") for folder_id in folder_ids}
    ids = QuestionService(session, provider=None)._canonical_document_ids(filters, metadata)
    assert ids == set(world.documents.values())
    sql = " ".join(statements).upper()
    assert "DISTINCT" not in sql and "EXISTS" in sql
