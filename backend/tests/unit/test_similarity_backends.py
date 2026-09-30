from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.knowledge.questions import _cosine_similarity
from app.knowledge.similarity import PythonSimilarity, default_similarity


def test_python_scores_and_sqlite_flag_fallback():
    rows = [(None, SimpleNamespace(id=uuid4(), embedding=vector)) for vector in ([1., 2.], [2., 1.], [0., 0.])]
    with Session(create_engine('sqlite://')) as session:
        index = default_similarity(session, SimpleNamespace(vector_backend='pgvector'))
        assert isinstance(index, PythonSimilarity)
        assert index.scores(session, filters=[], question_embedding=[1., 2.], rows=rows) == {
            chunk.id: _cosine_similarity([1., 2.], chunk.embedding) for _, chunk in rows
        }


class CountingSimilarity(PythonSimilarity):
    def __init__(self):
        self.calls = 0

    def scores(self, session, *, filters, question_embedding, rows):
        self.calls += 1
        return super().scores(session, filters=filters, question_embedding=question_embedding, rows=rows)


def test_question_computes_the_similarity_map_once():
    from sqlalchemy.pool import StaticPool

    from app.core.models import Base
    from app.core.scoping import OrganizationScope
    from app.knowledge.questions import QuestionService
    from tests.unit.test_semantic_questions import FakeProvider, chunk, context

    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        org, user, folder = context(session)
        for index, vector in enumerate(([1.0, 0.0], [0.8, 0.2], [0.1, 0.9])):
            chunk(session, org, folder, name=f'plan-{index}.pdf', text=f'Launch plan {index}', embedding=vector)
        provider = FakeProvider({'When is the launch?': [1.0, 0.0]})
        similarity = CountingSimilarity()
        result = QuestionService(session, provider, similarity=similarity).ask(
            scope=OrganizationScope(org.id), user_id=user.id,
            workspace_folder_id=folder.id, question='When is the launch?',
        )
        assert result.citations
        assert similarity.calls == 1
    engine.dispose()
