"""The folder structure an organization admin picks from when granting library folders to a Space.

Metadata only (folder names, never files or content): roots of each synchronization and the subfolders of any
catalog folder of the organization. Callers check the admin role; nothing here is reachable by members.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.core.sqlids import ids_clause
from app.library.models import LibraryNode
from app.workspaces.models import WorkspaceFolder, WorkspaceFolderSelection

MAX_SUBFOLDERS = 500


@dataclass(frozen=True)
class FolderNodeView:
    id: UUID
    name: str
    has_children: bool
    source_id: UUID


def _views(session: Session, organization_id: UUID, nodes: list[LibraryNode]) -> list[FolderNodeView]:
    if not nodes:
        return []
    child = aliased(LibraryNode)
    parents_with_folders = set(session.scalars(
        select(child.parent_id).where(
            child.organization_id == organization_id, child.kind == "folder",
            ids_clause(session, child.parent_id, [node.id for node in nodes])).distinct()))
    return [FolderNodeView(node.id, node.name, node.id in parents_with_folders, node.source_id) for node in nodes]


def sync_roots(session: Session, organization_id: UUID) -> dict[UUID, list[FolderNodeView]]:
    """Synchronization (workspace folder) -> the library folders it was built from, by name."""
    scopes = {scope.id: scope for scope in session.scalars(select(WorkspaceFolder).where(
        WorkspaceFolder.organization_id == organization_id))}
    if not scopes:
        return {}
    selections: dict[UUID, list[WorkspaceFolderSelection]] = {}
    for selection in session.scalars(select(WorkspaceFolderSelection).where(
            ids_clause(session, WorkspaceFolderSelection.workspace_folder_id, scopes))):
        selections.setdefault(selection.workspace_folder_id, []).append(selection)
    folders = {(node.source_id, node.external_id): node for node in session.scalars(
        select(LibraryNode).where(
            LibraryNode.organization_id == organization_id, LibraryNode.kind == "folder",
            ids_clause(session, LibraryNode.source_id, {scope.source_id for scope in scopes.values()})))}
    source_roots = {node.source_id: node.id for node in session.scalars(select(LibraryNode).where(
        LibraryNode.organization_id == organization_id, LibraryNode.kind == "source"))}
    top_level: dict[UUID, list[LibraryNode]] = {}
    for node in folders.values():
        if node.parent_id is not None and node.parent_id == source_roots.get(node.source_id):
            top_level.setdefault(node.source_id, []).append(node)
    chosen: dict[UUID, list[LibraryNode]] = {}
    for scope_id, scope in scopes.items():
        found: dict[UUID, LibraryNode] = {}
        for selection in selections.get(scope_id, ()):
            if selection.kind == "folder":
                node = folders.get((scope.source_id, selection.external_folder_id))
                if node is not None:
                    found[node.id] = node
            elif selection.kind == "all_accessible":
                found.update({node.id: node for node in top_level.get(scope.source_id, ())})
        chosen[scope_id] = sorted(found.values(), key=lambda node: (node.name.casefold(), str(node.id)))
    everything = {node.id: node for nodes in chosen.values() for node in nodes}
    views = {view.id: view for view in _views(session, organization_id, list(everything.values()))}
    return {scope_id: [views[node.id] for node in nodes] for scope_id, nodes in chosen.items()}


def subfolders(session: Session, organization_id: UUID, node_id: UUID) -> list[FolderNodeView] | None:
    """Direct subfolders of a catalog folder (None when the node is not a folder of this organization)."""
    parent = session.scalar(select(LibraryNode).where(
        LibraryNode.id == node_id, LibraryNode.organization_id == organization_id,
        LibraryNode.kind.in_(("folder", "source"))))
    if parent is None:
        return None
    rows = list(session.scalars(select(LibraryNode).where(
        LibraryNode.organization_id == organization_id, LibraryNode.parent_id == parent.id,
        LibraryNode.kind == "folder").order_by(LibraryNode.name, LibraryNode.id).limit(MAX_SUBFOLDERS)))
    return _views(session, organization_id, rows)

