"""M55: library file nodes without any `documents` row (orphans) are pruned or re-ingested."""
# ruff: noqa: F811  (pytest fixture imported from tests.sync_helpers)

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.ingestion.service import IngestionService
from app.integrations.models import DataSource
from app.library.models import LibraryNode
from app.library.service import LibraryService
from tests.sync_helpers import (  # noqa: F401
    T0,
    TREE,
    doc,
    seed,
    session,
    space,
    statuses,
    sync,
)


def file_ids(session: Session) -> set[str]:
    return {node.external_id for node in session.scalars(
        select(LibraryNode).where(LibraryNode.kind == "file"))}


def add_orphan(session: Session, organization, source, external_id: str, *, parent: str = "tda") -> None:
    """A catalog file whose `documents` row vanished (e.g. a removed workspace)."""
    folder = session.scalar(select(LibraryNode).where(LibraryNode.external_id == parent))
    session.add(LibraryNode(
        organization_id=organization.id, source_id=source.id, parent_id=folder.id,
        external_id=external_id, kind="file", name=f"{external_id}.pdf",
        mime_type="application/pdf", source_url="",
    ))
    session.flush()


def test_removing_workspace_leaves_no_orphan_file_nodes(session: Session) -> None:
    organization, user, source = seed(session)
    gone = space(session, organization, source, "gone", created_at=T0, folder_id="tda")
    sync(session, organization, user, gone, [doc("a"), doc("b", parent="sub")])
    assert file_ids(session) == {"a", "b"}

    IngestionService(session).remove_workspace(
        scope=OrganizationScope(organization.id), user_id=user.id, workspace_folder_id=gone.id)

    assert file_ids(session) == set()
    # The emptied folder metadata goes with its files; the source root stays.
    assert {node.kind for node in session.scalars(select(LibraryNode))} == {"source"}


def test_removing_workspace_keeps_files_another_workspace_still_indexes(session: Session) -> None:
    organization, user, source = seed(session)
    keeper = space(session, organization, source, "keeper", created_at=T0)
    gone = space(session, organization, source, "gone", created_at=T0, folder_id="tda")
    sync(session, organization, user, keeper, [doc("shared")])
    sync(session, organization, user, gone, [doc("shared"), doc("only-here")])

    IngestionService(session).remove_workspace(
        scope=OrganizationScope(organization.id), user_id=user.id, workspace_folder_id=gone.id)

    assert file_ids(session) == {"shared"}
    assert statuses(session, keeper) == {"shared": "indexed"}


def test_full_snapshot_prunes_unseen_nodes_without_documents(session: Session) -> None:
    """The 34 production nodes: created by a workspace that is gone, never listed again."""
    organization, user, source = seed(session)
    workspace = space(session, organization, source, "all", created_at=T0)
    sync(session, organization, user, workspace, [doc("seen")])
    add_orphan(session, organization, source, "ghost")
    assert file_ids(session) == {"seen", "ghost"}

    sync(session, organization, user, workspace, [doc("seen")], full_snapshot=True)

    assert file_ids(session) == {"seen"}


def test_full_snapshot_keeps_unseen_node_that_another_workspace_indexed(session: Session) -> None:
    organization, user, source = seed(session)
    wide = space(session, organization, source, "wide", created_at=T0)
    narrow = space(session, organization, source, "narrow", created_at=T0, folder_id="sub")
    sync(session, organization, user, wide, [doc("deep", parent="sub"), doc("top")])
    sync(session, organization, user, narrow, [doc("other", parent="sub")], full_snapshot=True)

    assert file_ids(session) == {"deep", "top", "other"}


def test_full_snapshot_indexes_seen_node_that_has_no_document(session: Session) -> None:
    organization, user, source = seed(session)
    workspace = space(session, organization, source, "all", created_at=T0)
    sync(session, organization, user, workspace, [doc("seen")])
    add_orphan(session, organization, source, "pending")

    sync(session, organization, user, workspace, [doc("seen"), doc("pending")], full_snapshot=True)

    assert statuses(session, workspace) == {"seen": "indexed", "pending": "indexed"}
    assert file_ids(session) == {"seen", "pending"}


def test_delta_does_not_prune_unseen_nodes(session: Session) -> None:
    organization, user, source = seed(session)
    workspace = space(session, organization, source, "all", created_at=T0)
    sync(session, organization, user, workspace, [doc("seen")])
    add_orphan(session, organization, source, "ghost")

    sync(session, organization, user, workspace, [doc("seen")], full_snapshot=False)

    assert file_ids(session) == {"seen", "ghost"}


def test_delta_prunes_orphan_the_source_no_longer_serves(session: Session) -> None:
    organization, user, source = seed(session)
    workspace = space(session, organization, source, "all", created_at=T0)
    sync(session, organization, user, workspace, [doc("seen")])
    add_orphan(session, organization, source, "ghost")
    add_orphan(session, organization, source, "other")
    library = LibraryService(session)

    assert library.orphan_file_ids(organization_id=organization.id, source_id=source.id) == {
        "ghost", "other"}
    library.project_successful_sync(
        organization_id=organization.id, source=session.get(DataSource, source.id),
        documents=[], folders=TREE, workspace_folder_id=workspace.id,
        full_snapshot=False, removed_file_ids={"ghost", "seen"},
    )

    # Only the orphan the source reported gone; a file that still has a document is never touched here.
    assert file_ids(session) == {"seen", "other"}


def test_orphan_file_ids_ignores_files_with_documents_in_any_workspace(session: Session) -> None:
    organization, user, source = seed(session)
    first = space(session, organization, source, "first", created_at=T0, folder_id="tda")
    second = space(session, organization, source, "second", created_at=T0 + timedelta(minutes=1))
    sync(session, organization, user, first, [doc("a")])
    sync(session, organization, user, second, [doc("b")])
    add_orphan(session, organization, source, "ghost")

    assert LibraryService(session).orphan_file_ids(
        organization_id=organization.id, source_id=source.id) == {"ghost"}


def test_management_command_previews_then_prunes_idempotently(session: Session) -> None:
    from scripts.reconcile_library_orphans import reconcile

    organization, user, source = seed(session)
    workspace = space(session, organization, source, "all", created_at=T0)
    sync(session, organization, user, workspace, [doc("seen")])
    add_orphan(session, organization, source, "ghost")

    assert reconcile(session) == {source.id: 1}
    assert file_ids(session) == {"seen", "ghost"}  # dry-run changes nothing
    assert reconcile(session, apply=True) == {source.id: 1}
    assert file_ids(session) == {"seen"}
    assert reconcile(session, apply=True) == {}
