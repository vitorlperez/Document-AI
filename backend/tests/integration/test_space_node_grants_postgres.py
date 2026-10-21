"""PostgreSQL coverage of folder-level grants: recursive CTEs, ANY(array) and the document predicate on real SQL."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

import app.audit_usage.models
import app.automations.models
import app.notifications.models  # noqa: F401
from app.core.access_errors import SyncAccessDenied
from app.core.models import Base
from app.knowledge.retrieval import RetrievalService
from app.library.models import LibraryNode
from app.library.service import LibraryService
from app.spaces.readable import partial_folder_ids
from tests.space_node_helpers import Tree

pytestmark = pytest.mark.postgres


@pytest.fixture()
def session(test_database_url):
    engine = create_engine(test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:  # the migration-managed full-text column that metadata does not declare
        connection.execute(text(
            "ALTER TABLE document_chunks ADD COLUMN search_vector tsvector "
            "GENERATED ALWAYS AS (to_tsvector('simple', coalesce(search_text, ''))) STORED"))
    database: Session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield database
    database.rollback()
    database.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_subtree_grant_on_postgres_reads_descendants_only(session):
    tree = Tree(session)
    tree.grant(session, "rh", tree.y2026)
    service, user = LibraryService(session), tree.world.users["bruno"]
    access = tree.access(session, "bruno")
    assert partial_folder_ids(session, access) == {tree.shared}
    assert tree.visible(session, "bruno", tree.contratos) == {"2026"}
    assert tree.visible(session, "bruno", tree.y2026) == {"c2026.pdf"}
    with pytest.raises(SyncAccessDenied):
        service.children(scope=tree.scope, user_id=user, parent_id=tree.financeiro, page=1, page_size=50)
    selection = service.resolve_question_selection(
        scope=tree.scope, user_id=user, providers=["google_drive"], mentions=[])
    hits = RetrievalService(session).search(scope=tree.scope, user_id=user, query="contrato", selection=selection)
    assert {hit.title for hit in hits} == {"c2026.pdf"}
    outsider = service.resolve_question_selection(
        scope=tree.scope, user_id=tree.world.users["daniel"], providers=["google_drive"], mentions=[])
    assert RetrievalService(session).search(
        scope=tree.scope, user_id=tree.world.users["daniel"], query="contrato", selection=outsider) == []
    snapshots = service.catalog_file_snapshots(
        scope=tree.scope, user_id=user, providers=["google_drive"], node_ids=[tree.node["c2026"]])
    assert [item.document_id for item in snapshots] == [tree.doc["c2026"]]
    with pytest.raises(SyncAccessDenied):
        service.catalog_file_snapshots(
            scope=tree.scope, user_id=user, providers=["google_drive"], node_ids=[tree.node["balanco"]])


def test_parent_grant_inherits_to_loose_files_and_subfolders_on_postgres(session):
    tree = Tree(session)
    tree.grant(session, "rh", tree.contratos)
    assert tree.visible(session, "bruno", tree.contratos) == {"2026", "solto.pdf"}
    badges = LibraryService(session).spaces_for_nodes(
        scope=tree.scope, nodes=[session.get(LibraryNode, tree.node["c2026"])], access=tree.access(session, "bruno"))
    assert [ref.name for ref in badges[tree.node["c2026"]]] == ["RH"]
