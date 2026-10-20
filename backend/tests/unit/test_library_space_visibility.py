"""T-D1..D4 + A1: the library tree, name search, provenance, mentions and catalog snapshots follow the Spaces."""

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.access_errors import SyncAccessDenied
from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.knowledge.models import Document
from app.library.models import LibraryNode
from app.library.service import LibraryService
from app.organizations.models import Organization
from app.spaces.access import SpaceAccessResolver
from tests.spaces_helpers import seed_world

EXPECTED = {
    "eva": {"politicas"},
    "ana": {"politicas", "rh"},
    "bruno": {"politicas", "rh"},
    "carla": {"politicas", "rh", "diretoria"},
    "daniel": {"politicas", "diretoria"},
}


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    database = sessionmaker(bind=engine, expire_on_commit=False)()
    yield database
    database.close()
    engine.dispose()


def names(nodes):
    return {node.name for node in nodes}


def files(*keys):
    return {f"{key}.pdf" for key in keys}


def tree(session, world, who, **kw):
    service = LibraryService(session)
    scope, user = OrganizationScope(world.organization_id), world.users[who]
    roots = service.roots(scope=scope, user_id=user, **kw)
    kids = service.children(scope=scope, user_id=user, parent_id=world.nodes["source"], page=1, page_size=50, **kw)
    return roots, kids


@pytest.mark.parametrize("who", sorted(EXPECTED))
def test_children_are_the_files_of_readable_scopes(session, who):
    world = seed_world(session)
    roots, kids = tree(session, world, who)
    assert [r.id for r in roots] == [world.nodes["source"]]
    assert names(kids.items) == files(*EXPECTED[who])
    assert kids.total == len(EXPECTED[who])


def test_total_and_pages_follow_the_filtered_set(session):
    world = seed_world(session)
    service = LibraryService(session)
    scope, user = OrganizationScope(world.organization_id), world.users["bruno"]
    page = service.children(scope=scope, user_id=user, parent_id=world.nodes["source"], page=2, page_size=1)
    assert (page.total, page.pages, len(page.items)) == (2, 2, 1)


def test_a_source_without_visible_children_is_not_a_root(session):
    world = seed_world(session)
    from app.spaces.models import SpaceMember
    session.query(SpaceMember).filter_by(user_id=world.users["bruno"]).update({"removed_at": __import__("datetime").datetime.now()})
    session.flush()
    roots, kids = tree(session, world, "bruno")
    assert roots == [] and kids.items == []


def test_off_and_shadow_keep_the_whole_tree(session):
    world = seed_world(session)
    for mode in ("off", "shadow"):
        session.get(Organization, world.organization_id).spaces_resolver_mode = mode
        session.flush()
        _, kids = tree(session, world, "bruno")
        assert names(kids.items) == files("politicas", "rh", "diretoria")


def test_uncatalogued_nodes_are_for_admins_only(session):
    world = seed_world(session)
    session.add(LibraryNode(organization_id=world.organization_id, source_id=world.nodes and
                            session.get(LibraryNode, world.nodes["source"]).source_id,
                            parent_id=world.nodes["source"], external_id="pending-1", kind="file", name="pending.pdf"))
    session.flush()
    assert "pending.pdf" in names(tree(session, world, "eva")[1].items)
    assert "pending.pdf" not in names(tree(session, world, "bruno")[1].items)


def test_removed_documents_hide_the_file(session):
    world = seed_world(session)
    session.get(Document, world.documents["rh"]).index_status = "removed"
    session.flush()
    assert names(tree(session, world, "bruno")[1].items) == files("politicas")


def test_file_in_two_scopes_shows_once_and_provenance_is_limited(session):
    world = seed_world(session)
    # the Diretoria file is also indexed in the Geral scope: Bruno (Geral, RH) now reaches it through Geral only
    copy = Document(organization_id=world.organization_id, workspace_folder_id=world.folders["politicas"],
                    external_file_id="diretoria-doc", name="diretoria.pdf", mime_type="application/pdf",
                    source_url="u", content_hash="b" * 64, processing_version="v1", index_status="indexed")
    session.add(copy)
    session.flush()
    service = LibraryService(session)
    scope = OrganizationScope(world.organization_id)
    node = session.get(LibraryNode, world.nodes["diretoria"])
    for who, expected in (("bruno", {world.folders["politicas"]}),
                          ("carla", {world.folders["politicas"], world.folders["diretoria"]})):
        access = SpaceAccessResolver(session).resolve(scope=scope, user_id=world.users[who])
        _, kids = tree(session, world, who)
        assert [n.name for n in kids.items].count("diretoria.pdf") == 1
        assert set(service.workspace_provenance(scope=scope, node=node, access=access)) == expected
        assert {p.workspace_folder_id for p in service.document_provenance(scope=scope, node=node, access=access)} == expected
        documents, indexing = service.documents_and_indexing_for_nodes(scope=scope, nodes=[node], access=access)
        assert {p.workspace_folder_id for p in documents[node.id]} == expected
        assert indexing[node.id].workspace_folder_id in expected


def test_indexed_documents_under_only_returns_readable_scopes(session):
    world = seed_world(session)
    service = LibraryService(session)
    scope = OrganizationScope(world.organization_id)
    found = service.indexed_documents_under(scope=scope, user_id=world.users["bruno"], node_id=world.nodes["source"],
                                            allow_source=True)
    assert {item.workspace_folder_id for item in found} == {world.folders["politicas"], world.folders["rh"]}


@pytest.mark.parametrize("who", sorted(EXPECTED))
def test_name_search_only_finds_visible_nodes_and_counts_only_them(session, who):
    world = seed_world(session)
    service = LibraryService(session)
    scope, user = OrganizationScope(world.organization_id), world.users[who]
    page = service.search_page(scope=scope, user_id=user, query="pdf", page=1, page_size=50)
    assert names(page.items) == files(*EXPECTED[who]) and page.total == len(EXPECTED[who])
    hidden = service.search_page(scope=scope, user_id=user, query="diretoria", page=1, page_size=50)
    assert hidden.total == (1 if "diretoria" in EXPECTED[who] else 0)


def test_name_search_narrows_with_space_filter(session):
    world = seed_world(session)
    service = LibraryService(session)
    scope, user = OrganizationScope(world.organization_id), world.users["carla"]
    access = SpaceAccessResolver(session).resolve(scope=scope, user_id=user, space_ids=[world.spaces["rh"]])
    page = service.search_page(scope=scope, user_id=user, query="pdf", page=1, page_size=50, access=access)
    assert names(page.items) == files("rh")


def test_mention_of_a_hidden_node_is_rejected_like_a_missing_one(session):
    world = seed_world(session)
    service = LibraryService(session)
    scope = OrganizationScope(world.organization_id)
    with pytest.raises(ValueError, match="mention is unavailable"):
        service.resolve_question_selection(scope=scope, user_id=world.users["bruno"], providers=["google_drive"],
                                           mentions=[("file", world.nodes["diretoria"])])
    with pytest.raises(ValueError, match="mention is unavailable"):
        service.resolve_question_selection(scope=scope, user_id=world.users["bruno"], providers=["google_drive"],
                                           mentions=[("file", world.nodes["diretoria"]), ("file", world.nodes["rh"])])


def test_node_map_loaded_for_mentions_is_the_visible_one(session):
    world = seed_world(session)
    service = LibraryService(session)
    scope = OrganizationScope(world.organization_id)
    access = SpaceAccessResolver(session).resolve(scope=scope, user_id=world.users["daniel"])
    assert set(service._selection_nodes(scope=scope, access=access)) == {
        world.nodes["source"], world.nodes["politicas"], world.nodes["diretoria"]}


# --- A1: catalog snapshots follow the person's Spaces, not the whole organization ----------------------
@pytest.mark.parametrize("validate", [True, False])
def test_catalog_snapshot_of_a_node_outside_my_spaces_is_denied(session, validate):
    world = seed_world(session)
    service = LibraryService(session)
    scope, user = OrganizationScope(world.organization_id), world.users["bruno"]
    with pytest.raises(SyncAccessDenied):
        service.catalog_file_snapshots(scope=scope, user_id=user, providers=["google_drive"],
                                       node_ids=[world.nodes["diretoria"]], validate_references=validate)


def test_catalog_snapshot_of_my_node_still_reads_it(session):
    world = seed_world(session)
    out = LibraryService(session).catalog_file_snapshots(
        scope=OrganizationScope(world.organization_id), user_id=world.users["bruno"], providers=["google_drive"],
        node_ids=[world.nodes["rh"]])
    assert out[0].index_status == "indexed" and "salarial" in out[0].excerpt


def test_authorized_catalog_never_contains_hidden_nodes(session):
    world = seed_world(session)
    catalog = LibraryService(session).authorized_catalog(
        scope=OrganizationScope(world.organization_id), user_id=world.users["bruno"], providers=["google_drive"],
        mentions=[])
    assert world.nodes["diretoria"] not in catalog.nodes and world.nodes["diretoria"] not in catalog.all_nodes
    assert world.folders["diretoria"] not in catalog.folder_ids


def test_tree_statement_count_does_not_grow_with_the_number_of_files(session):
    world = seed_world(session)
    source_id = session.get(LibraryNode, world.nodes["source"]).source_id
    for index in range(40):
        session.add(LibraryNode(organization_id=world.organization_id, source_id=source_id,
                                parent_id=world.nodes["source"], external_id=f"x{index}", kind="file", name=f"x{index}.pdf"))
    session.flush()
    seen: list[str] = []
    event.listen(session.get_bind(), "before_cursor_execute", lambda c, cur, st, p, ctx, m: seen.append(st))
    tree(session, world, "eva")
    assert len(seen) <= 14, len(seen)
