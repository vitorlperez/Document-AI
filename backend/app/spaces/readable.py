"""Document-level reading rights: whole scopes plus library folders granted with everything below them.

A document is readable when its scope (WorkspaceFolder) is granted whole (``access.folder_ids``) OR it is a copy of a
file under a granted library folder (``access.node_grants``) of the same source. This is the one predicate content
queries add; ``access.folder_ids`` alone means "whole scopes only" and never includes a partially granted scope, so
anything that has not adopted this module fails closed.
"""

from collections.abc import Collection, Mapping
from uuid import UUID

from sqlalchemy import ColumnElement, Select, and_, exists, false, or_, select
from sqlalchemy.orm import Session, aliased

from app.core.sqlids import ids_clause
from app.knowledge.models import Document
from app.library.models import LibraryNode
from app.spaces.access import SpaceAccess
from app.workspaces.models import WorkspaceFolder


def granted_subtree(session: Session, organization_id: UUID, node_ids: Collection[UUID]) -> Select:
    """``select(id)`` of the nodes (roots included) at any depth below ``node_ids``."""
    tree = select(LibraryNode.id).where(
        LibraryNode.organization_id == organization_id, ids_clause(session, LibraryNode.id, node_ids),
    ).cte(recursive=True)
    child = aliased(LibraryNode)
    tree = tree.union(select(child.id).where(
        child.parent_id == tree.c.id, child.organization_id == organization_id))
    return select(tree.c.id)


def documents_under_nodes(
    session: Session, organization_id: UUID, node_ids: Collection[UUID], document=Document
) -> ColumnElement[bool]:
    """Correlated predicate on ``document``: a copy of a file below one of ``node_ids`` (same source)."""
    if not node_ids:
        return false()
    file_node = aliased(LibraryNode)
    scope = aliased(WorkspaceFolder)
    return exists(
        select(file_node.id).select_from(file_node).join(scope, scope.source_id == file_node.source_id)
        .where(file_node.id.in_(granted_subtree(session, organization_id, node_ids)),
               file_node.kind == "file", file_node.organization_id == organization_id,
               file_node.external_id == document.external_file_id,
               scope.id == document.workspace_folder_id, scope.organization_id == organization_id))


# Above this many granted files the ids are no longer inlined in the statement (see ``granted_files``).
MAX_INLINE_FILES = 20_000


def granted_files(session: Session, access: SpaceAccess) -> Mapping[UUID, frozenset[str]]:
    """source id -> external ids of the files below the granted folders: ONE recursive query per request (memoized).

    Content queries filter ``documents`` with these ids (``uq_documents_folder_external`` is then an index lookup)
    instead of re-running the recursive subtree and a join for every statement."""
    found = access.memo.get("granted_files")
    if found is None:
        files: dict[UUID, set[str]] = {}
        if access.node_grants:
            file_node = aliased(LibraryNode)
            for source_id, external_id in session.execute(
                select(file_node.source_id, file_node.external_id).where(
                    file_node.id.in_(granted_subtree(session, access.organization_id, access.node_ids)),
                    file_node.kind == "file", file_node.organization_id == access.organization_id)):
                files.setdefault(source_id, set()).add(external_id)
        found = {source_id: frozenset(ids) for source_id, ids in files.items()}
        access.memo["granted_files"] = found
    return found


def _source_scopes(session: Session, access: SpaceAccess, source_ids: Collection[UUID]) -> Mapping[UUID, frozenset[UUID]]:
    found = access.memo.get("source_scopes")
    if found is None:
        scopes: dict[UUID, set[UUID]] = {}
        for scope_id, source_id in session.execute(select(WorkspaceFolder.id, WorkspaceFolder.source_id).where(
                WorkspaceFolder.organization_id == access.organization_id, ids_clause(session, WorkspaceFolder.source_id, source_ids))):
            scopes.setdefault(source_id, set()).add(scope_id)
        found = {source_id: frozenset(ids) for source_id, ids in scopes.items()}
        access.memo["source_scopes"] = found
    return found


def documents_in_grants(session: Session, access: SpaceAccess, document=Document) -> ColumnElement[bool]:
    """Predicate on ``document``: a copy of a file below one of the person's granted folders (same source).

    Inlines the materialized ids (``granted_files``) so PostgreSQL walks ``uq_documents_folder_external`` rather than
    scanning every document of the organization; past ``MAX_INLINE_FILES`` it keeps the correlated subquery."""
    if not access.node_grants:
        return false()
    files = granted_files(session, access)
    if sum(len(ids) for ids in files.values()) > MAX_INLINE_FILES:
        return documents_under_nodes(session, access.organization_id, access.node_ids, document)
    scopes = _source_scopes(session, access, files)
    parts = [and_(ids_clause(session, document.workspace_folder_id, scopes[source_id]),
                  ids_clause(session, document.external_file_id, ids))
             for source_id, ids in files.items() if ids and scopes.get(source_id)]
    return or_(*parts) if parts else false()


def readable_document_clause(session: Session, access: SpaceAccess, document=Document) -> ColumnElement[bool]:
    """Predicate on ``document`` rows the person may read (whole scopes or files below a granted folder)."""
    whole = ids_clause(session, document.workspace_folder_id, access.folder_ids)
    if not access.node_grants:
        return whole
    if not access.folder_ids:  # only folder grants: no empty ``= ANY('{}')`` branch to keep the planner off the index
        return documents_in_grants(session, access, document)
    return or_(whole, documents_in_grants(session, access, document))


def partial_folder_ids(session: Session, access: SpaceAccess) -> frozenset[UUID]:
    """Scopes the person reads only in part: not granted whole, but holding documents below a granted folder
    (memoized per request: several consumers ask for it)."""
    if not access.node_grants:
        return frozenset()
    found = access.memo.get("partial_folder_ids")
    if found is None:
        scopes = set(session.scalars(
            select(Document.workspace_folder_id).where(
                Document.organization_id == access.organization_id,
                Document.index_status.not_in(("removed", "deleted")),
                documents_in_grants(session, access)).distinct()))
        found = frozenset(scopes - access.folder_ids)
        access.memo["partial_folder_ids"] = found
    return found


def node_spaces_of_files(
    session: Session, access: SpaceAccess, files: Collection[tuple[UUID, str]]
) -> dict[tuple[UUID, str], set[UUID]]:
    """(source, external id) -> the person's Spaces that grant the file through a library folder."""
    if not access.node_grants or not files:
        return {}
    org = access.organization_id
    below = select(LibraryNode.id.label("root"), LibraryNode.id.label("node")).where(
        LibraryNode.organization_id == org, ids_clause(session, LibraryNode.id, access.node_ids),
    ).cte(recursive=True)
    child = aliased(LibraryNode)
    below = below.union(select(below.c.root, child.id).where(
        child.parent_id == below.c.node, child.organization_id == org))
    file_node = aliased(LibraryNode)
    wanted = {external for _, external in files}
    found: dict[tuple[UUID, str], set[UUID]] = {}
    keys = set(files)
    for root_id, source_id, external_id in session.execute(
        select(below.c.root, file_node.source_id, file_node.external_id)
        .select_from(below).join(file_node, file_node.id == below.c.node)
        .where(file_node.kind == "file", ids_clause(session, file_node.external_id, wanted)).distinct()
    ):
        if (source_id, external_id) in keys:
            found.setdefault((source_id, external_id), set()).update(access.node_grants.get(root_id, ()))
    return found


def ancestor_chains(
    session: Session, organization_id: UUID, node_ids: Collection[UUID]
) -> dict[UUID, tuple[UUID, ...]]:
    """Node -> (itself, parent, grandparent, ...) for each id, one query per tree level."""
    chains: dict[UUID, list[UUID]] = {node_id: [node_id] for node_id in node_ids}
    heads = {node_id: node_id for node_id in chains}
    seen: dict[UUID, UUID | None] = {}
    pending = set(heads.values())
    while pending:
        rows = session.execute(select(LibraryNode.id, LibraryNode.parent_id).where(
            LibraryNode.organization_id == organization_id, ids_clause(session, LibraryNode.id, pending))).all()
        seen.update(dict(rows))
        pending = set()
        for node_id, head in list(heads.items()):
            parent = seen.get(head)
            if parent is None or parent in chains[node_id]:
                heads.pop(node_id)
                continue
            chains[node_id].append(parent)
            heads[node_id] = parent
            if parent not in seen:
                pending.add(parent)
    return {node_id: tuple(chain) for node_id, chain in chains.items()}


class NodeGrantBadges:
    """Which of the person's Spaces grant a node through a library folder (inheritance down, partial up)."""

    def __init__(self, session: Session, access: SpaceAccess):
        self.session, self.access = session, access
        self.granted = ancestor_chains(session, access.organization_id, access.node_ids) if access.node_grants else {}
        self.sources: dict[UUID, set[UUID]] = {}
        if self.granted:
            for node_id, source_id in session.execute(select(LibraryNode.id, LibraryNode.source_id).where(
                    LibraryNode.organization_id == access.organization_id,
                    ids_clause(session, LibraryNode.id, self.granted))):
                self.sources.setdefault(source_id, set()).update(access.node_grants.get(node_id, ()))

    def for_nodes(self, nodes: Collection[LibraryNode]) -> dict[UUID, set[UUID]]:
        """node id -> space ids. A node is badged by a grant when the granted folder is the node or above it
        (it is inside the Space), or below it (the Space reads part of what it holds)."""
        if not self.granted:
            return {}
        picked = [node for node in nodes if node.kind != "source"]
        chains = ancestor_chains(self.session, self.access.organization_id, [node.id for node in picked])
        found: dict[UUID, set[UUID]] = {}
        for node in picked:
            spaces: set[UUID] = set()
            chain = chains.get(node.id, (node.id,))
            for granted_id, granted_chain in self.granted.items():
                if granted_id in chain or node.id in granted_chain:
                    spaces.update(self.access.node_grants.get(granted_id, ()))
            if spaces:
                found[node.id] = spaces
        return found

    def for_source(self, source_id: UUID) -> set[UUID]:
        return self.sources.get(source_id, set())
