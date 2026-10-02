"""Shared query admission, including committed content from an active sync."""
from sqlalchemy import exists, or_, select

from app.knowledge.models import Document, DocumentChunk
from app.workspaces.models import WorkspaceFolder


def folder_is_queryable(folder=None, session=None, *, has_embeddings=None):
    # Local import avoids the questions -> library -> questions dependency.
    from app.knowledge.questions import EMBEDDING_MODEL

    embedded = exists(select(DocumentChunk.id).join(
        Document, Document.id == DocumentChunk.document_id,
    ).where(
        Document.organization_id == WorkspaceFolder.organization_id,
        Document.workspace_folder_id == WorkspaceFolder.id,
        Document.index_status == "indexed",
        DocumentChunk.organization_id == WorkspaceFolder.organization_id,
        DocumentChunk.workspace_folder_id == WorkspaceFolder.id,
        DocumentChunk.embedding.is_not(None),
        DocumentChunk.embedding_model == EMBEDDING_MODEL,
    )).correlate(WorkspaceFolder)
    predicate = or_(WorkspaceFolder.status.in_(["ready", "partial_failure"]),
                    (WorkspaceFolder.status == "syncing") & embedded)
    if folder is None:
        return predicate
    if folder.status in {"ready", "partial_failure"}:
        return True
    if folder.status != "syncing":
        return False
    if has_embeddings is not None:
        return bool(has_embeddings)
    if hasattr(folder, "query_status"):
        return folder.query_status == "ready"
    return bool(session.scalar(select(WorkspaceFolder.id).where(
        WorkspaceFolder.id == folder.id,
        WorkspaceFolder.organization_id == folder.organization_id,
        predicate,
    )))
