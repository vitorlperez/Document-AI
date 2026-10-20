"""T-B3 (skeleton): no surface returns anything outside the person's reachable set (ADR-0021 I1/I3).

The library tree and name search (Block D) are now part of the matrix. Evidence/viewer, API key and MCP
surfaces join in later waves.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.access_errors import SyncAccessDenied
from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.library.service import LibraryService
from tests.spaces_helpers import seed_world

# who -> the folders they may reach (Acme example, ADR-0021 §7.2)
EXPECTED = {
    "eva": {"politicas"},
    "ana": {"politicas", "rh"},
    "bruno": {"politicas", "rh"},
    "carla": {"politicas", "rh", "diretoria"},
    "daniel": {"politicas", "diretoria"},
}
PEOPLE = sorted(EXPECTED)


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    database = sessionmaker(bind=engine, expire_on_commit=False)()
    yield database
    database.close()
    engine.dispose()


def reachable(world, who):
    return {world.folders[name] for name in EXPECTED[who]}


@pytest.mark.parametrize("who", PEOPLE)
def test_question_contexts_are_exactly_the_reachable_folders(session, who):
    world = seed_world(session)
    contexts = LibraryService(session).question_contexts(
        scope=OrganizationScope(world.organization_id), user_id=world.users[who])
    assert {c.id for c in contexts} == reachable(world, who)


@pytest.mark.parametrize("who", PEOPLE)
def test_question_selection_only_admits_reachable_folders(session, who):
    world = seed_world(session)
    selection = LibraryService(session).resolve_question_selection(
        scope=OrganizationScope(world.organization_id), user_id=world.users[who],
        providers=["google_drive"], mentions=[])
    assert set(selection.folder_ids) <= reachable(world, who)


@pytest.mark.parametrize("who", PEOPLE)
def test_mention_candidates_never_name_an_unreachable_file(session, who):
    world = seed_world(session)
    candidates = LibraryService(session).mention_candidates(
        scope=OrganizationScope(world.organization_id), user_id=world.users[who], query=".pdf")
    allowed_names = {f"{name}.pdf" for name in EXPECTED[who]}
    assert {c.node.name for c in candidates if c.node.kind == "file"} <= allowed_names


@pytest.mark.parametrize("who", PEOPLE)
def test_mention_of_an_unreachable_file_is_rejected_like_a_missing_one(session, who):
    world = seed_world(session)
    service = LibraryService(session)
    for name, node_id in world.nodes.items():
        if name == "source" or name in EXPECTED[who]:
            continue
        with pytest.raises(ValueError):
            service.resolve_question_selection(
                scope=OrganizationScope(world.organization_id), user_id=world.users[who],
                providers=["google_drive"], mentions=[("file", node_id)])


@pytest.mark.parametrize("who", PEOPLE)
def test_library_tree_and_search_hide_unreachable_files(session, who):
    world = seed_world(session)
    service = LibraryService(session)
    scope, user = OrganizationScope(world.organization_id), world.users[who]
    root = service.roots(scope=scope, user_id=user)[0]
    children = service.children(scope=scope, user_id=user, parent_id=root.id, page=1, page_size=50).items
    allowed = {f"{name}.pdf" for name in EXPECTED[who]}
    assert {node.name for node in children} == allowed
    found = service.search_page(scope=scope, user_id=user, query="pdf", page=1, page_size=50).items
    assert {node.name for node in found} <= allowed


@pytest.mark.parametrize("who", PEOPLE)
def test_catalog_snapshots_never_read_an_unreachable_file(session, who):
    """A1: authorization is the person's Spaces, not the organization."""
    world = seed_world(session)
    service = LibraryService(session)
    scope, user = OrganizationScope(world.organization_id), world.users[who]
    for name in ("politicas", "rh", "diretoria"):
        call = lambda: service.catalog_file_snapshots(
            scope=scope, user_id=user, providers=["google_drive"], node_ids=[world.nodes[name]])  # noqa: B023
        if name in EXPECTED[who]:
            assert call()[0].index_status == "indexed"
        else:
            with pytest.raises(SyncAccessDenied):
                call()
