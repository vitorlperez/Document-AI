"""Spike M1/M3: the question path asks the database for the top-K chunks instead of loading every chunk."""

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.knowledge.models import Document, DocumentChunk
from app.knowledge.questions import EMBEDDING_MODEL, MAX_SEMANTIC_CANDIDATES, QuestionService
from app.knowledge.similarity import PythonSimilarity
from tests.unit.test_semantic_questions import FakeProvider, context


class TopKSimilarity(PythonSimilarity):
    """Reads ids only (no entities) so the test can observe how many chunks the service hydrates."""

    def __init__(self):
        self.top_calls = 0
        self.score_rows: list[int] = []

    def top(self, session, *, filters, question_embedding, limit):
        self.top_calls += 1
        ids = list(session.execute(
            select(DocumentChunk.id).join(Document, Document.id == DocumentChunk.document_id)
            .where(*filters).order_by(DocumentChunk.id).limit(limit)).scalars())
        return {chunk_id: 0.9 for chunk_id in ids}

    def scores(self, session, *, filters, question_embedding, rows):
        self.score_rows.append(len(rows))
        return super().scores(session, filters=filters, question_embedding=question_embedding, rows=rows)


@pytest.fixture()
def seeded():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        org, user, folder = context(session)
        for index in range(150):
            document = Document(
                organization_id=org.id, workspace_folder_id=folder.id, external_file_id=str(uuid4()),
                name=f"doc-{index}.pdf", mime_type="application/pdf", source_url="https://x.test",
                content_hash="a" * 64, processing_version="v1", index_status="indexed")
            session.add(document)
            session.flush()
            for position in range(4):
                session.add(DocumentChunk(
                    organization_id=org.id, workspace_folder_id=folder.id, document_id=document.id,
                    position=position, text=f"launch plan {index} part {position}", search_text=f"launch plan {index}",
                    embedding=[1.0, 0.0], embedding_model=EMBEDDING_MODEL))
        session.commit()
        yield session, org, user, folder
    engine.dispose()


def test_ask_hydrates_only_the_top_k_candidates(seeded):
    session, org, user, folder = seeded
    similarity = TopKSimilarity()
    loaded: list[object] = []
    event.listen(DocumentChunk, "load", lambda target, ctx: loaded.append(target))
    result = QuestionService(session, FakeProvider({"launch?": [1.0, 0.0]}), similarity=similarity).ask(
        scope=OrganizationScope(org.id), user_id=user.id, workspace_folder_id=folder.id, question="launch?")
    assert result.citations
    assert similarity.top_calls == 1
    # 600 chunks exist; only candidates (+ lexical hits + neighbour windows) may be hydrated.
    assert len(loaded) < 600 / 2, len(loaded)
    assert len(loaded) >= MAX_SEMANTIC_CANDIDATES
    assert max(similarity.score_rows, default=0) < 600  # never a full similarity map over all chunks


def test_python_backend_top_matches_full_ranking(seeded):
    session, org, _user, _folder = seeded
    top = PythonSimilarity().top(
        session, filters=[Document.organization_id == org.id, DocumentChunk.organization_id == org.id],
        question_embedding=[1.0, 0.0], limit=5)
    assert len(top) == 5 and all(abs(score - 1.0) < 1e-9 for score in top.values())
