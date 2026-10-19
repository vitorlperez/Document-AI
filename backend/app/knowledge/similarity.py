"""One similarity map per question, scoped identically in both backends."""
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import ColumnElement, Text, cast, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.vector import EMBEDDING_DIMENSIONS, cosine_similarity_expr
from app.knowledge.models import Document, DocumentChunk


class SimilarityIndex(Protocol):
    def scores(self, session: Session, *, filters: Sequence[ColumnElement[bool]],
               question_embedding: list[float], rows: Sequence[tuple[Document, DocumentChunk]]) -> dict[UUID, float]: ...

    def top(self, session: Session, *, filters: Sequence[ColumnElement[bool]],
            question_embedding: list[float], limit: int) -> dict[UUID, float]:
        """The ``limit`` best chunks under ``filters`` as {chunk_id: score}, best first (ties by id)."""
        ...


class PythonSimilarity:
    def scores(self, session, *, filters, question_embedding, rows):
        from app.knowledge.questions import _cosine_similarity
        return {chunk.id: _cosine_similarity(question_embedding, chunk.embedding or []) for _, chunk in rows}

    def top(self, session, *, filters, question_embedding, limit):
        rows = list(session.execute(
            select(Document, DocumentChunk).join(DocumentChunk, DocumentChunk.document_id == Document.id).where(*filters)
        ).all())
        scores = self.scores(session, filters=filters, question_embedding=question_embedding, rows=rows)
        best = sorted(scores.items(), key=lambda item: (-item[1], str(item[0])))[:limit]
        return dict(best)


class PgVectorSimilarity:
    """Scores computed in PostgreSQL. A chunk the backfill has not reached yet (embedding_vec
    NULL) is cast from its JSON embedding in the query, so it is scored instead of silently
    dropped; once backfilled, the stored vector is used."""

    def scores(self, session, *, filters, question_embedding, rows):
        vector = func.coalesce(
            DocumentChunk.embedding_vec, cast(cast(DocumentChunk.embedding, Text), Vector(EMBEDDING_DIMENSIONS)),
        )
        statement = (select(DocumentChunk.id, cosine_similarity_expr(vector, question_embedding))
                     .join(Document, Document.id == DocumentChunk.document_id)
                     .where(*filters, or_(DocumentChunk.embedding_vec.is_not(None),
                                          func.json_typeof(DocumentChunk.embedding) == "array")))
        return {chunk_id: float(score or 0.0) for chunk_id, score in session.execute(statement)}

    def top(self, session, *, filters, question_embedding, limit):
        """Top-K in SQL: only ``limit`` (id, score) pairs leave the database (spike M1)."""
        vector = func.coalesce(
            DocumentChunk.embedding_vec, cast(cast(DocumentChunk.embedding, Text), Vector(EMBEDDING_DIMENSIONS)),
        )
        score = cosine_similarity_expr(vector, question_embedding)
        statement = (select(DocumentChunk.id, score.label("score"))
                     .join(Document, Document.id == DocumentChunk.document_id)
                     .where(*filters, or_(DocumentChunk.embedding_vec.is_not(None),
                                          func.json_typeof(DocumentChunk.embedding) == "array"))
                     .order_by(score.desc(), DocumentChunk.id).limit(limit))
        return {chunk_id: float(value or 0.0) for chunk_id, value in session.execute(statement)}


def default_similarity(session, settings=None):
    """pgvector only on PostgreSQL with VECTOR_BACKEND=pgvector; SQLite never reads settings."""
    if session.get_bind().dialect.name != 'postgresql':
        return PythonSimilarity()
    settings = settings or get_settings()
    return PgVectorSimilarity() if settings.vector_backend == 'pgvector' else PythonSimilarity()
