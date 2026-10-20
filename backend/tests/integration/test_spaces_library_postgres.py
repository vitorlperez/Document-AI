"""PostgreSQL coverage of the Space-aware library (recursive CTEs, ANY(:ids), DISTINCT ON) on the Acme world."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.access_errors import SyncAccessDenied
from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.ingestion.models import ProcessingJob, ProcessingJobStatus
from app.library.service import LibraryService
from tests.spaces_helpers import seed_world

pytestmark = pytest.mark.postgres

EXPECTED = {"eva": {"politicas"}, "ana": {"politicas", "rh"}, "bruno": {"politicas", "rh"},
            "carla": {"politicas", "rh", "diretoria"}, "daniel": {"politicas", "diretoria"}}


@pytest.fixture()
def session(test_database_url):
    engine = create_engine(test_database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    database: Session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield database
    database.rollback()
    database.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.mark.parametrize("who", sorted(EXPECTED))
def test_tree_search_mentions_and_snapshots_follow_the_spaces(session, who):
    world = seed_world(session)
    service = LibraryService(session)
    scope, user = OrganizationScope(world.organization_id), world.users[who]
    allowed = {f"{name}.pdf" for name in EXPECTED[who]}
    roots = service.roots(scope=scope, user_id=user)
    kids = service.children(scope=scope, user_id=user, parent_id=world.nodes["source"], page=1, page_size=50)
    assert [r.id for r in roots] == [world.nodes["source"]]
    assert {n.name for n in kids.items} == allowed and kids.total == len(allowed)
    found = service.search_page(scope=scope, user_id=user, query="pdf", page=1, page_size=50)
    assert {n.name for n in found.items} == allowed and found.total == len(allowed)
    mentions = service.mention_candidates(scope=scope, user_id=user, query="pdf")
    assert {c.node.name for c in mentions if c.node.kind == "file"} == allowed
    assert {c.node.name for c in service.mention_candidates(scope=scope, user_id=user, query="google")
            if c.node.kind == "file"} == allowed  # a match through the ancestor's name still lists the files below
    catalog = service.authorized_catalog(scope=scope, user_id=user, providers=["google_drive"], mentions=[])
    assert {n.name for n in catalog.nodes.values() if n.kind == "file"} == allowed
    for name in ("politicas", "rh", "diretoria"):
        call = lambda: service.catalog_file_snapshots(  # noqa: E731
            scope=scope, user_id=user, providers=["google_drive"], node_ids=[world.nodes[name]])
        if name in EXPECTED[who]:
            assert call()[0].index_status == "indexed"
        else:
            with pytest.raises(SyncAccessDenied):
                call()
    under = service.indexed_documents_under(scope=scope, user_id=user, node_id=world.nodes["source"], allow_source=True)
    assert {item.workspace_folder_id for item in under} == {world.folders[name] for name in EXPECTED[who]}


def test_sync_status_and_history_use_distinct_on_per_scope(session):
    world = seed_world(session)
    for key, folder_id in world.folders.items():
        session.add(ProcessingJob(organization_id=world.organization_id, workspace_folder_id=folder_id,
                                  status=ProcessingJobStatus.READY, idempotency_key=f"job-{key}"))
    session.flush()
    service = LibraryService(session)
    scope = OrganizationScope(world.organization_id)
    assert {s.workspace_name for s in service.recent_syncs(scope=scope, user_id=world.users["bruno"])} == {"politicas", "rh"}
    assert len(service.sync_status(scope=scope, user_id=world.users["bruno"])) == 1
    assert {s.workspace_name for s in service.recent_syncs(scope=scope, user_id=world.users["eva"])} == {
        "politicas", "rh", "diretoria"}
