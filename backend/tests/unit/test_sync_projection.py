"""Invariant (c): library projection only prunes files removed at the source."""
# ruff: noqa: F811  (pytest fixture imported from tests.sync_helpers)


from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.google_drive import RemoteFolder
from app.library.models import LibraryNode
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


# (c): incremental sync never removes unchanged nodes nor nodes of other spaces.
def test_incremental_sync_keeps_unchanged_nodes_and_other_space_nodes(session: Session) -> None:
    organization, user, source = seed(session)
    drive = space(session, organization, source, "drive", created_at=T0)
    tda = space(session, organization, source, "tda", created_at=T0, folder_id="tda")
    other_tree = [RemoteFolder("logo", "LOGO"), RemoteFolder("empty", "Empty")]
    sync(session, organization, user, drive, [doc("logo-1", parent="logo")], folders=other_tree)
    sync(session, organization, user, tda, [doc("a"), doc("b", parent="sub")])

    # Delta containing only one changed file.
    sync(session, organization, user, tda, [doc("a", text="novo")], full_snapshot=False)

    nodes = {node.external_id for node in session.scalars(select(LibraryNode))}
    assert {"logo", "empty", "logo-1", "tda", "sub", "a", "b"} <= nodes
    assert statuses(session, tda) == {"a": "indexed", "b": "indexed"}


def test_projection_removes_only_files_removed_at_the_source(session: Session) -> None:
    organization, user, source = seed(session)
    tda = space(session, organization, source, "tda", created_at=T0, folder_id="tda")
    drive = space(session, organization, source, "drive", created_at=T0)
    sync(session, organization, user, tda, [doc("a"), doc("b", parent="sub")])
    sync(session, organization, user, drive, [doc("a")], folders=TREE)

    sync(session, organization, user, tda, [], full_snapshot=True, folders=TREE[:1])

    nodes = {node.external_id for node in session.scalars(select(LibraryNode))}
    assert "b" not in nodes and "sub" not in nodes  # gone at the source, empty folder pruned
    assert {"a", "tda"} <= nodes  # still indexed by the other space
