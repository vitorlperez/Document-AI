"""pgvector on PostgreSQL, JSON lists on SQLite."""
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Float, type_coerce
from sqlalchemy.types import TypeDecorator

EMBEDDING_DIMENSIONS = 1536


class EmbeddingVector(TypeDecorator):
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(Vector(EMBEDDING_DIMENSIONS) if dialect.name == 'postgresql' else JSON())

    def process_result_value(self, value, dialect):
        return None if value is None else [float(item) for item in value]


def cosine_similarity_expr(column, vector: list[float]):
    return 1 - column.op('<=>', return_type=Float())(type_coerce(vector, Vector(EMBEDDING_DIMENSIONS)))
