"""Spaces at folder level: a library folder granted to a Space brings only what is below it, fail-closed.

World: one synchronization ("shared", granted to nobody) holds files of a Drive tree
``Contratos/(solto.pdf, 2026/c2026.pdf)`` and ``Financeiro/balanco.pdf``. RH is granted ``Contratos/2026`` only.
"""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.audit_usage.models
import app.automations.models
import app.notifications.models  # noqa: F401
from app.core.access_errors import SyncAccessDenied
from app.core.models import Base
from app.knowledge.derived_visibility import Provenance, build_index
from app.knowledge.models import Document
from app.knowledge.retrieval import RetrievalService
from app.knowledge.space_seals import spaces_by_document
from app.library.models import LibraryNode
from app.library.service import LibraryService
from app.spaces.models import SpaceNodeGrant
from app.spaces.readable import partial_folder_ids
from app.spaces.service import SpaceDenied, SpaceNotFound, SpaceService
from tests.space_node_helpers import Tree
from tests.spaces_helpers import seed_world


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    database = sessionmaker(bind=engine, expire_on_commit=False)()
    yield database
    database.close()
    engine.dispose()


def test_node_grant_is_inheritance_over_the_subtree_and_leaves_whole_scopes_alone(session):
    tree = Tree(session)
    tree.grant(session, "rh", tree.y2026)
    access = tree.access(session, "bruno")
    assert access.node_grants == {tree.y2026: frozenset({tree.world.spaces["rh"]})}
    assert tree.shared not in access.folder_ids  # the scope is read in part, never whole
    assert partial_folder_ids(session, access) == {tree.shared}
    assert tree.access(session, "daniel").node_grants == {}  # not in RH: nothing


def test_granted_folder_shows_only_its_descendants_and_ancestors_as_path(session):
    tree = Tree(session)
    tree.grant(session, "rh", tree.y2026)
    assert tree.visible(session, "bruno", tree.world.nodes["source"]) >= {"Contratos"}
    assert "Financeiro" not in tree.visible(session, "bruno", tree.world.nodes["source"])
    assert tree.visible(session, "bruno", tree.contratos) == {"2026"}  # the loose file next to it is not granted
    assert tree.visible(session, "bruno", tree.y2026) == {"c2026.pdf"}


def test_sibling_not_granted_is_denied_like_a_node_that_does_not_exist(session):
    tree = Tree(session)
    tree.grant(session, "rh", tree.y2026)
    service, user = LibraryService(session), tree.world.users["bruno"]
    with pytest.raises(SyncAccessDenied):
        service.children(scope=tree.scope, user_id=user, parent_id=tree.financeiro, page=1, page_size=50)
    with pytest.raises(SyncAccessDenied):
        service.locate(scope=tree.scope, user_id=user, node_id=tree.node["balanco"])
    with pytest.raises(SyncAccessDenied):
        service.locate(scope=tree.scope, user_id=user, document_id=tree.doc["solto"])
    assert not any(node.name == "balanco.pdf" for node in service.search_names(
        scope=tree.scope, user_id=user, query="balanco"))


def test_person_outside_the_space_sees_nothing_of_the_granted_folder(session):
    tree = Tree(session)
    tree.grant(session, "rh", tree.y2026)
    service = LibraryService(session)
    for who in ("daniel", "eva"):  # eva is org owner but not in RH: still nothing
        user = tree.world.users[who]
        with pytest.raises(SyncAccessDenied):
            service.children(scope=tree.scope, user_id=user, parent_id=tree.y2026, page=1, page_size=50)
        assert not service.search_names(scope=tree.scope, user_id=user, query="2026") or who == "eva"
        assert service.indexed_documents_under(
            scope=tree.scope, user_id=user, node_id=tree.contratos) == [] if who == "daniel" else True


def test_granting_the_parent_brings_loose_files_and_subfolders(session):
    tree = Tree(session)
    tree.grant(session, "rh", tree.contratos)
    assert tree.visible(session, "bruno", tree.contratos) == {"2026", "solto.pdf"}
    assert tree.visible(session, "bruno", tree.y2026) == {"c2026.pdf"}
    assert "Financeiro" not in tree.visible(session, "bruno", tree.world.nodes["source"])


def test_revoked_grant_or_removed_member_or_archived_space_cuts_access(session):
    tree = Tree(session)
    tree.grant(session, "rh", tree.y2026)
    from datetime import UTC, datetime

    from app.spaces.models import Space, SpaceMember
    assert tree.access(session, "bruno").node_grants
    session.query(SpaceMember).filter_by(space_id=tree.world.spaces["rh"], user_id=tree.world.users["bruno"]).update(
        {"removed_at": datetime.now(UTC)})
    session.flush()
    assert tree.access(session, "bruno").node_grants == {}
    assert tree.access(session, "ana").node_grants  # still a member
    session.query(SpaceNodeGrant).update({"revoked_at": datetime.now(UTC)})
    session.flush()
    assert tree.access(session, "ana").node_grants == {}
    session.query(SpaceNodeGrant).update({"revoked_at": None})
    session.get(Space, tree.world.spaces["rh"]).archived_at = datetime.now(UTC)
    session.flush()
    assert tree.access(session, "ana").node_grants == {}


def test_grant_naming_a_folder_missing_from_the_catalog_grants_nothing(session):
    tree = Tree(session)
    tree.grant(session, "rh", tree.y2026)
    session.delete(session.get(LibraryNode, tree.y2026))
    session.flush()
    assert tree.access(session, "bruno").node_grants == {}  # fail-closed: no node, no access
    session.add(LibraryNode(organization_id=tree.world.organization_id, source_id=tree.world.source_id,
                            parent_id=tree.contratos, external_id="fld-2026", kind="folder", name="2026"))
    session.flush()
    assert len(tree.access(session, "bruno").node_grants) == 1  # the same provider folder is granted again


def test_a_file_is_never_a_grant_even_if_a_row_says_so(session):
    tree = Tree(session)
    node = session.get(LibraryNode, tree.node["balanco"])
    session.add(SpaceNodeGrant(organization_id=tree.world.organization_id, space_id=tree.world.spaces["rh"],
                               source_id=node.source_id, external_id=node.external_id, name="x", disclosure={}))
    session.flush()
    assert tree.access(session, "bruno").node_grants == {}


def search(session, tree, who, query):
    library = LibraryService(session)
    selection = library.resolve_question_selection(
        scope=tree.scope, user_id=tree.world.users[who], providers=["google_drive"], mentions=[])
    return selection, RetrievalService(session).search(
        scope=tree.scope, user_id=tree.world.users[who], query=query, selection=selection)


def test_search_and_fetch_return_only_granted_descendants(session):
    tree = Tree(session)
    tree.grant(session, "rh", tree.y2026)
    selection, hits = search(session, tree, "bruno", "contrato")
    assert selection.partial_folder_ids == (tree.shared,) and tree.shared not in selection.folder_ids
    assert {hit.title for hit in hits} == {"c2026.pdf"}  # the loose contract in the parent is not granted
    assert search(session, tree, "bruno", "balanco")[1] == []
    assert search(session, tree, "daniel", "contrato")[1] == []
    fetch = RetrievalService(session).fetch
    user = tree.world.users["bruno"]
    assert fetch(scope=tree.scope, user_id=user, document_id=tree.doc["c2026"], selection=selection)
    assert fetch(scope=tree.scope, user_id=user, document_id=tree.doc["solto"], selection=selection) is None
    assert fetch(scope=tree.scope, user_id=user, document_id=tree.doc["balanco"], selection=selection) is None


def test_mentions_inside_the_grant_work_and_outside_are_rejected(session):
    tree = Tree(session)
    tree.grant(session, "rh", tree.y2026)
    library, user = LibraryService(session), tree.world.users["bruno"]
    chosen = library.resolve_question_selection(
        scope=tree.scope, user_id=user, providers=["google_drive"], mentions=[("folder", tree.y2026)])
    assert chosen.document_ids == {tree.doc["c2026"]}
    with pytest.raises(ValueError):
        library.resolve_question_selection(
            scope=tree.scope, user_id=user, providers=["google_drive"], mentions=[("folder", tree.financeiro)])
    with pytest.raises(ValueError):  # the parent is visible as a path, but its loose content is not granted
        library.resolve_question_selection(
            scope=tree.scope, user_id=user, providers=["google_drive"], mentions=[("file", tree.node["solto"])])


def test_catalog_snapshots_and_mention_candidates_follow_the_grant(session):
    tree = Tree(session)
    tree.grant(session, "rh", tree.y2026)
    library, user = LibraryService(session), tree.world.users["bruno"]
    got = library.catalog_file_snapshots(
        scope=tree.scope, user_id=user, providers=["google_drive"], node_ids=[tree.node["c2026"]])
    assert [item.document_id for item in got] == [tree.doc["c2026"]]
    for key in ("solto", "balanco"):
        with pytest.raises(SyncAccessDenied):
            library.catalog_file_snapshots(
                scope=tree.scope, user_id=user, providers=["google_drive"], node_ids=[tree.node[key]])
    names = {item.node.name for item in library.mention_candidates(scope=tree.scope, user_id=user, query="")}
    assert "c2026.pdf" in names and "balanco.pdf" not in names and "solto.pdf" not in names


def test_citation_badges_and_derived_visibility_follow_the_grant(session):
    tree = Tree(session)
    tree.grant(session, "rh", tree.y2026)
    access = tree.access(session, "bruno")
    sealed = spaces_by_document(session, access, [tree.doc["c2026"], tree.doc["solto"]])
    assert [ref.name for ref in sealed[tree.doc["c2026"]]] == ["RH"] and sealed[tree.doc["solto"]] == ()
    index = build_index(session, access, [])
    assert index.partial_folders == {tree.shared}
    granted = Provenance(document_ids=frozenset({tree.doc["c2026"]}), folder_ids=frozenset({tree.shared}),
                         node_ids=frozenset({tree.node["c2026"]}))
    outside = Provenance(document_ids=frozenset({tree.doc["solto"]}), folder_ids=frozenset({tree.shared}))
    mixed = Provenance(document_ids=frozenset({tree.doc["c2026"], tree.doc["balanco"]}))
    folder_only = Provenance(folder_ids=frozenset({tree.shared}))  # a scope alone never vouches for a derivative
    index = build_index(session, access, [granted, outside, mixed, folder_only])
    assert index.visible(granted)
    assert not index.visible(outside) and not index.visible(mixed) and not index.visible(folder_only)


def test_reach_counts_only_granted_files(session):
    from sqlalchemy import func

    from app.spaces.readable import readable_document_clause
    tree = Tree(session)
    tree.grant(session, "rh", tree.y2026)
    access = tree.access(session, "bruno")
    count = session.scalar(select(func.count()).select_from(Document).where(
        Document.workspace_folder_id == tree.shared, readable_document_clause(session, access)))
    assert count == 1


def test_service_grants_only_catalog_folders_of_the_organization_and_only_by_admins(session):
    tree = Tree(session)
    other = seed_world(session, name="Globex")
    foreign = session.scalar(select(LibraryNode.id).where(
        LibraryNode.organization_id == other.organization_id, LibraryNode.kind == "source"))
    service, scope = SpaceService(session), tree.scope
    admin, member = tree.world.users["eva"], tree.world.users["bruno"]
    rh = tree.world.spaces["rh"]
    with pytest.raises(SpaceDenied):  # a node of another organization
        service.grant_node(scope, admin, rh, foreign, {"text_version": "v1"})
    with pytest.raises(SpaceDenied):  # a file is not a folder
        service.grant_node(scope, admin, rh, tree.node["balanco"], {"text_version": "v1"})
    with pytest.raises(SpaceDenied):  # a source root is not a folder
        service.grant_node(scope, admin, rh, tree.world.nodes["source"], {"text_version": "v1"})
    with pytest.raises(SpaceDenied):  # only organization admins
        service.grant_node(scope, member, rh, tree.y2026, {"text_version": "v1"})
    first = service.grant_node(scope, admin, rh, tree.y2026, {"text_version": "v1"})
    assert service.grant_node(scope, admin, rh, tree.y2026, {"text_version": "v1"}).id == first.id  # idempotent
    granted, revoked = service.apply_node_changes(scope, admin, rh, [tree.contratos], [tree.y2026], {"text_version": "v1"})
    assert granted == [tree.contratos] and revoked == [tree.y2026]
    views = service.node_grants(scope, tree.world.users["bruno"], rh)  # members see the grant list
    assert [(view.name, view.path) for view in views] == [("Contratos", "Google Drive/Contratos")]
    with pytest.raises(SpaceNotFound):  # daniel is not in RH: uniform not found
        service.node_grants(scope, tree.world.users["daniel"], rh)
