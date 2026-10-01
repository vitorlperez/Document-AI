import os
import random
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import build_engine
from app.identity.models import User
from app.integrations.models import DataSource
from app.knowledge.models import Document, DocumentChunk
from app.knowledge.questions import EMBEDDING_MODEL
from app.knowledge.similarity import PgVectorSimilarity, PythonSimilarity
from app.organizations.models import Organization
from app.workspaces.models import WorkspaceFolder
from scripts.backfill_pgvector import backfill

pytestmark = pytest.mark.postgres

BACKEND_DIR = Path(__file__).resolve().parents[2]
DIMENSIONS = 1536


def run_alembic(*arguments: str, database_url: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_DIR, env=os.environ | {"DATABASE_URL": database_url},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture()
def engine(test_database_url: str):
    run_alembic("downgrade", "base", database_url=test_database_url)
    run_alembic("upgrade", "head", database_url=test_database_url)
    value = build_engine(Settings(database_url=test_database_url))
    yield value
    value.dispose()
    run_alembic("downgrade", "base", database_url=test_database_url)


def random_vector(rng: random.Random) -> list[float]:
    return [rng.uniform(-1, 1) for _ in range(DIMENSIONS)]


def folder_for(session: Session, organization: Organization, user: User) -> WorkspaceFolder:
    source = DataSource(organization_id=organization.id, provider="google", encrypted_credentials="cipher", status="connected", connected_by_user_id=user.id)
    session.add(source); session.flush()
    folder = WorkspaceFolder(organization_id=organization.id, source_id=source.id, external_folder_id=str(uuid4()), name="Project", uniform_access_confirmed=True, status="ready")
    session.add(folder); session.flush()
    return folder


def seed(session: Session, folder: WorkspaceFolder, vectors: list[list[float]], *, dual_write: bool) -> None:
    document = Document(organization_id=folder.organization_id, workspace_folder_id=folder.id, external_file_id=str(uuid4()), name=f"{uuid4()}.pdf", mime_type="application/pdf", source_url="https://drive.example.test/doc", content_hash="a" * 64, processing_version="v1", index_status="indexed")
    session.add(document); session.flush()
    session.add_all(
        DocumentChunk(
            organization_id=folder.organization_id, workspace_folder_id=folder.id, document_id=document.id,
            position=position, text=f"chunk {position}", search_text=f"chunk {position}",
            embedding=vector, embedding_vec=vector if dual_write else None, embedding_model=EMBEDDING_MODEL,
        )
        for position, vector in enumerate(vectors)
    )
    session.flush()


def tenant(session: Session) -> tuple[Organization, User]:
    organization, user = Organization(name="Acme"), User(email=f"user-{uuid4()}@example.test")
    session.add_all([organization, user]); session.flush()
    return organization, user


def test_expand_migration_adds_and_drops_the_vector_column(test_database_url: str) -> None:
    run_alembic("downgrade", "base", database_url=test_database_url)
    try:
        run_alembic("upgrade", "head", database_url=test_database_url)
        engine = create_engine(test_database_url)
        columns = {column["name"]: column for column in inspect(engine).get_columns("document_chunks")}
        assert {"embedding", "embedding_vec"} <= columns.keys()
        with engine.connect() as connection:
            assert connection.scalar(text(
                "select format_type(atttypid, atttypmod) from pg_attribute "
                "where attrelid = 'document_chunks'::regclass and attname = 'embedding_vec'"
            )) == "vector(1536)"
            assert connection.scalar(text(
                "select count(*) from pg_indexes where tablename = 'document_chunks' and indexdef ilike '%embedding_vec%'"
            )) == 0
        engine.dispose()
        run_alembic("downgrade", "20260929_0018", database_url=test_database_url)
        engine = create_engine(test_database_url)
        columns = {column["name"] for column in inspect(engine).get_columns("document_chunks")}
        assert "embedding" in columns and "embedding_vec" not in columns
        engine.dispose()
        run_alembic("upgrade", "head", database_url=test_database_url)
    finally:
        run_alembic("downgrade", "base", database_url=test_database_url)


def test_type_round_trip_and_self_similarity(engine) -> None:
    rng = random.Random(7)
    vector = random_vector(rng)
    with Session(engine) as session:
        organization, user = tenant(session)
        folder = folder_for(session, organization, user)
        seed(session, folder, [vector], dual_write=True)
        session.commit()
        stored = session.scalar(select(DocumentChunk.embedding_vec))
        assert stored == pytest.approx(vector, abs=1e-6)
        scores = PgVectorSimilarity().scores(
            session, filters=[Document.organization_id == organization.id],
            question_embedding=vector, rows=[],
        )
        assert list(scores.values()) == [pytest.approx(1.0, abs=1e-6)]


def test_backfill_is_resumable_and_skips_chunks_without_embedding(engine) -> None:
    rng = random.Random(11)
    with Session(engine) as session:
        organization, user = tenant(session)
        folder = folder_for(session, organization, user)
        seed(session, folder, [random_vector(rng) for _ in range(2500)], dual_write=False)
        empty = session.scalars(select(DocumentChunk).limit(1)).one()
        empty.embedding = None
        session.commit()
    assert backfill(engine, batch=1000, sleep_seconds=0) == 2499
    assert backfill(engine, batch=1000, sleep_seconds=0) == 0
    with Session(engine) as session:
        for chunk in session.scalars(select(DocumentChunk)):
            if chunk.embedding is None:
                assert chunk.embedding_vec is None
            else:
                assert chunk.embedding_vec == pytest.approx(chunk.embedding, abs=1e-6)


def test_pgvector_matches_python_and_keeps_tenants_apart(engine) -> None:
    rng = random.Random(42)
    with Session(engine) as session:
        organization, user = tenant(session)
        folders = [folder_for(session, organization, user) for _ in range(2)]
        for folder in folders:
            seed(session, folder, [random_vector(rng) for _ in range(150)], dual_write=True)
        other_organization, other_user = tenant(session)
        seed(session, folder_for(session, other_organization, other_user), [random_vector(rng) for _ in range(50)], dual_write=True)
        session.commit()

        filters = [
            Document.organization_id == organization.id,
            DocumentChunk.organization_id == organization.id,
            Document.workspace_folder_id.in_([folder.id for folder in folders]),
            DocumentChunk.embedding.is_not(None),
            DocumentChunk.embedding_model == EMBEDDING_MODEL,
        ]
        rows = list(session.execute(
            select(Document, DocumentChunk).join(DocumentChunk, DocumentChunk.document_id == Document.id).where(*filters)
        ).all())
        question = random_vector(rng)
        expected = PythonSimilarity().scores(session, filters=filters, question_embedding=question, rows=rows)
        actual = PgVectorSimilarity().scores(session, filters=filters, question_embedding=question, rows=[])

        assert len(expected) == 300
        assert actual.keys() == expected.keys()
        assert max(abs(actual[key] - expected[key]) for key in expected) <= 1e-5
        top = lambda scores: sorted(scores, key=lambda key: (-scores[key], str(key)))[:10]
        assert top(actual) == top(expected)
        other_ids = set(session.scalars(select(DocumentChunk.id).where(DocumentChunk.organization_id == other_organization.id)))
        assert len(other_ids) == 50 and not other_ids & actual.keys()


def test_pgvector_scores_chunks_the_backfill_has_not_reached(engine) -> None:
    rng = random.Random(23)
    vectors = [random_vector(rng) for _ in range(40)]
    question = random_vector(rng)
    with Session(engine) as session:
        organization, user = tenant(session)
        folder = folder_for(session, organization, user)
        seed(session, folder, vectors[:20], dual_write=True)
        seed(session, folder, vectors[20:], dual_write=False)  # written before dual-write, not backfilled
        session.commit()
        rows = session.execute(select(Document, DocumentChunk).join(DocumentChunk)).all()
        filters = [Document.organization_id == organization.id]
        python_scores = PythonSimilarity().scores(session, filters=filters, question_embedding=question, rows=rows)
        pg_scores = PgVectorSimilarity().scores(session, filters=filters, question_embedding=question, rows=rows)

    assert pg_scores.keys() == python_scores.keys() and len(pg_scores) == 40
    assert max(abs(pg_scores[key] - python_scores[key]) for key in pg_scores) <= 1e-5
