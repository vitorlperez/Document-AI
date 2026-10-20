from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.models import Base
from app.core.vector import EMBEDDING_DIMENSIONS
from app.knowledge.models import DocumentChunk
from scripts.seed_espacos_demo import widen_demo_embeddings
from tests.spaces_helpers import seed_world


def test_demo_chunks_have_the_dimension_pgvector_requires():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine).begin() as session:
        world = seed_world(session)
        assert {len(c.embedding) for c in session.scalars(select(DocumentChunk))} == {2}  # the test helper's fake vectors
        widen_demo_embeddings(session, world.organization_id)
        session.flush()
        chunks = list(session.scalars(select(DocumentChunk)))
        assert chunks
        for chunk in chunks:
            assert len(chunk.embedding) == len(chunk.embedding_vec) == EMBEDDING_DIMENSIONS
            assert chunk.embedding[:2] == [1.0, 0.0] and not any(chunk.embedding[2:])
