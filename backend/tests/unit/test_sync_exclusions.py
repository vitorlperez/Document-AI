"""Invariants (a)+(b): removals never hide a newer space; removing a space leaves no stale exclusion."""
# ruff: noqa: F811  (pytest fixture imported from tests.sync_helpers)

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.ingestion.service import IngestionService
from app.knowledge.models import DocumentChunk
from app.library.models import LibraryExclusion, LibraryNode
from app.library.service import LibraryService
from app.workspaces.models import WorkspaceFolderSelection
from tests.sync_helpers import (  # noqa: F401
    T0,
    TREE,
    doc,
    exclude,
    seed,
    session,
    space,
    statuses,
    sync,
)


# (a) + (b): an exclusion made before a space existed never hides that space's tree.
def test_new_space_discovers_tree_excluded_before_it_was_selected(session: Session) -> None:
    organization, user, source = seed(session)
    old = space(session, organization, source, "old", created_at=T0, folder_id="tda")
    exclude(session, organization, source, "tda", "folder", at=T0 + timedelta(minutes=1))
    exclude(session, organization, source, "a", "file", at=T0 + timedelta(minutes=1))
    library = LibraryService(session)

    kept_old, _ = library.filter_excluded_content(
        organization_id=organization.id, source_id=source.id, documents=[doc("a"), doc("b", parent="sub")],
        folders=TREE, workspace_folder_id=old.id)
    assert kept_old == []  # the space that existed when the user removed it keeps honouring it

    new = space(session, organization, source, "new", created_at=T0 + timedelta(minutes=2), folder_id="tda")
    sync(session, organization, user, new, [doc("a"), doc("b", parent="sub")])
    assert statuses(session, new) == {"a": "indexed", "b": "indexed"}
    assert {node.external_id for node in session.scalars(select(LibraryNode))} >= {"tda", "sub", "a", "b"}


# (b): "excluir dados locais" leaves no residual exclusion that could hide the next space.
def test_removing_space_forgets_exclusions_no_remaining_space_honours(session: Session) -> None:
    organization, user, source = seed(session)
    old = space(session, organization, source, "old", created_at=T0, folder_id="tda")
    sync(session, organization, user, old, [doc("a")])
    exclude(session, organization, source, "tda", "folder", at=T0 + timedelta(minutes=1))
    service = IngestionService(session)

    service.remove_workspace(scope=OrganizationScope(organization.id), user_id=user.id,
                             workspace_folder_id=old.id)

    assert session.scalars(select(LibraryExclusion)).all() == []
    assert session.scalars(select(DocumentChunk)).all() == []
    assert session.scalars(select(WorkspaceFolderSelection)).all() == []


def test_removing_space_keeps_exclusion_still_honoured_by_older_space(session: Session) -> None:
    organization, user, source = seed(session)
    keeper = space(session, organization, source, "keeper", created_at=T0)
    removed = space(session, organization, source, "removed", created_at=T0, folder_id="tda")
    exclude(session, organization, source, "tda", "folder", at=T0 + timedelta(minutes=1))

    IngestionService(session).remove_workspace(scope=OrganizationScope(organization.id),
                                               user_id=user.id, workspace_folder_id=removed.id)

    assert [item.external_id for item in session.scalars(select(LibraryExclusion))] == ["tda"]
    assert keeper.id is not None
