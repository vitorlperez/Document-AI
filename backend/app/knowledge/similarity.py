"""One similarity map per question, scoped identically in both backends."""
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from sqlalchemy import ColumnElement, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.vector import cosine_similarity_expr
from app.knowledge.models import Document, DocumentChunk


class SimilarityIndex(Protocol):
    def scores(self, session: Session, *, filters: Sequence[ColumnElement[bool]],
               question_embedding: list[float], rows: Sequence[tuple[Document, DocumentChunk]]) -> dict[UUID, float]: ...


class PythonSimilarity:
    def scores(self, session, *, filters, question_embedding, rows):
        from app.knowledge.questions import _cosine_similarity
        return {chunk.id: _cosine_similarity(question_embedding, chunk.embedding or []) for _, chunk in rows}


class PgVectorSimilarity:
    def scores(self, session, *, filters, question_embedding, rows):
        statement = (select(DocumentChunk.id, cosine_similarity_expr(DocumentChunk.embedding_vec, question_embedding))
                     .join(Document, Document.id == DocumentChunk.document_id)
                     .where(*filters, DocumentChunk.embedding_vec.is_not(None)))
        return {chunk_id: float(score or 0.0) for chunk_id, score in session.execute(statement)}


def default_similarity(session, settings=None):
    """pgvector only on PostgreSQL with VECTOR_BACKEND=pgvector; SQLite never reads settings."""
    if session.get_bind().dialect.name != 'postgresql':
        return PythonSimilarity()
    settings = settings or get_settings()
    return PgVectorSimilarity() if settings.vector_backend == 'pgvector' else PythonSimilarity()
