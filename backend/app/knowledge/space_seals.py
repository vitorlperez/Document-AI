"""Space seals for derived content: which of the caller's Spaces grant each cited document (ADR-0021 E2/E3).

A file present in several granted folders (same source, same external id) is one logical file: its seal is the
union of the caller's Spaces over all those copies. Only the caller's own Spaces are ever named.
"""

from collections.abc import Collection, Mapping
from dataclasses import replace
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.core.sqlids import ids_clause
from app.knowledge.models import Document
from app.spaces.access import SpaceAccess, SpaceAccessResolver, SpaceRef
from app.spaces.readable import node_spaces_of_files
from app.workspaces.models import WorkspaceFolder


def spaces_by_document(
    session: Session, access: SpaceAccess, document_ids: Collection[UUID]
) -> dict[UUID, tuple[SpaceRef, ...]]:
    """Two queries for any number of documents; ``()`` for every document when the person has no Spaces (legacy)."""
    ids = list(dict.fromkeys(document_ids))
    if not ids:
        return {}
    if not access.spaces:
        return {document_id: () for document_id in ids}
    own = session.execute(
        select(Document.id, Document.external_file_id, WorkspaceFolder.source_id)
        .join(WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id)
        .where(Document.organization_id == access.organization_id, ids_clause(session, Document.id, ids))
    ).all()
    files = {(source_id, external_id) for _, external_id, source_id in own}
    external_ids = {external_id for _, external_id in files}
    siblings: dict[tuple[UUID, str], set[UUID]] = {}
    if external_ids:
        rows = session.execute(
            select(Document.workspace_folder_id, Document.external_file_id, WorkspaceFolder.source_id)
            .join(WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id)
            .where(
                Document.organization_id == access.organization_id, Document.index_status == "indexed",
                ids_clause(session, Document.external_file_id, external_ids),
                ids_clause(session, Document.workspace_folder_id, access.folder_ids),
            )
        ).all()
        for folder_id, external_id, source_id in rows:
            siblings.setdefault((source_id, external_id), set()).add(folder_id)
    through_nodes = node_spaces_of_files(session, access, files)  # Spaces granting the file via a library folder
    sealed: dict[UUID, tuple[SpaceRef, ...]] = {}
    for document_id, external_id, source_id in own:
        refs: dict[UUID, SpaceRef] = {}
        for folder_id in siblings.get((source_id, external_id), ()):
            for ref in access.spaces_of(folder_id):
                refs[ref.id] = ref
        for space_id in through_nodes.get((source_id, external_id), ()):
            if space_id in access.spaces:
                refs[space_id] = access.spaces[space_id]
        sealed[document_id] = tuple(sorted(refs.values(), key=lambda ref: (ref.name.casefold(), str(ref.id))))
    return {document_id: sealed.get(document_id, ()) for document_id in ids}


def seal_citations(session: Session, access: SpaceAccess, result):
    """Return ``result`` with ``spaces`` set on every citation (a QuestionResult; untouched when it has none)."""
    if not result.citations:
        return result
    sealed = spaces_by_document(session, access, [item.document_id for item in result.citations])
    return replace(result, citations=[replace(item, spaces=sealed.get(item.document_id, ())) for item in result.citations])


def seal_result(session: Session, scope: OrganizationScope, user_id: UUID, result):
    """Seal a finished answer with the caller's Spaces (resolved under the request's own Space filter)."""
    if not result.citations:
        return result
    return seal_citations(session, SpaceAccessResolver(session).resolve(scope=scope, user_id=user_id), result)


def spaces_payload(spaces: Mapping | tuple | None) -> list[dict[str, str]]:
    return [{"id": str(ref.id), "name": ref.name} for ref in spaces or ()]
