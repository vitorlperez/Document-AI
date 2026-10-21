"""Which library nodes a person may see (ADR-0021 §4.4): the filter is SQL, never a Python post-filter.

A file is visible when some document of it lives in a scope the person can read; a folder (or a source root)
is visible when it has a visible descendant file. Owners/admins additionally see files no scope indexes at
all (catalogued, never synchronized into any scope): operational metadata, not content.
Spaces always enforce (decision 2026-10-20): there is no unfiltered answer.

v1 resolves ancestors with a recursive CTE over ``library_nodes``; a projection table can replace it behind
the same two functions if the scale benchmark ever asks for it (plan T-D6).
"""

from uuid import UUID

from sqlalchemy import ColumnElement, Select, exists, select
from sqlalchemy.orm import Session, aliased

from app.knowledge.models import Document
from app.library.models import LibraryNode
from app.spaces.access import SpaceAccess
from app.spaces.readable import readable_document_clause
from app.workspaces.models import WorkspaceFolder

GONE_STATUSES = ("removed", "deleted")


def _document_of_node(organization_id: UUID):
    return (
        Document.organization_id == organization_id,
        Document.external_file_id == LibraryNode.external_id,
        WorkspaceFolder.id == Document.workspace_folder_id,
        WorkspaceFolder.organization_id == organization_id,
        WorkspaceFolder.source_id == LibraryNode.source_id,
    )


def visible_file_clause(session: Session, access: SpaceAccess, organization_id: UUID) -> ColumnElement[bool]:
    """Correlated predicate on ``LibraryNode`` rows of kind file."""
    readable = exists(
        select(Document.id).select_from(Document).join(WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id)
        .where(*_document_of_node(organization_id), Document.index_status.not_in(GONE_STATUSES),
               readable_document_clause(session, access)))
    if not access.org_admin:
        return readable
    uncatalogued = ~exists(
        select(Document.id).select_from(Document).join(WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id)
        .where(*_document_of_node(organization_id)))
    return readable | uncatalogued


def visible_node_ids(session: Session, access: SpaceAccess, organization_id: UUID) -> Select:
    """``select(id)`` of every visible node (files and their ancestors)."""
    files = select(LibraryNode.id, LibraryNode.parent_id).where(
        LibraryNode.organization_id == organization_id, LibraryNode.kind == "file",
        visible_file_clause(session, access, organization_id)).cte("visible_nodes", recursive=True)
    parent = aliased(LibraryNode)
    tree = files.union(select(parent.id, parent.parent_id).where(
        parent.id == files.c.parent_id, parent.organization_id == organization_id))
    return select(tree.c.id)


def restrict_to_visible(session: Session, access: SpaceAccess, organization_id: UUID, statement: Select) -> Select:
    """Add the visibility filter to a ``select(LibraryNode)`` statement."""
    return statement.where(LibraryNode.id.in_(visible_node_ids(session, access, organization_id)))
