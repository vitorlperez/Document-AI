"""On-click evidence for a citation: the cited passage and where it lives, scoped to what the member may query."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.auth import current_user, database_session
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.ingestion.service import SyncAccessDenied
from app.integrations.models import DataSource
from app.knowledge.models import Document, DocumentChunk
from app.library.service import LibraryService
from app.spaces.access import SpaceAccessResolver
from app.spaces.readable import readable_document_clause
from app.workspaces.models import WorkspaceFolder

router = APIRouter(tags=['evidence'])
MAX_PASSAGE_CHARS = 4000


def scoped_document(session: Session, *, organization_id: UUID, document_id: UUID, user: User) -> Document:
    """The document only when the member may query its folder; 404 otherwise (never reveals existence)."""
    scope = OrganizationScope(organization_id)
    try:
        access = SpaceAccessResolver(session).resolve(scope=scope, user_id=user.id)
        contexts = LibraryService(session).question_contexts(
            scope=scope, user_id=user.id, access=access, include_partial=True)
    except SyncAccessDenied as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'evidence not found') from error
    document = session.scalar(select(Document)
        .join(WorkspaceFolder, WorkspaceFolder.id == Document.workspace_folder_id)
        .join(DataSource, DataSource.id == WorkspaceFolder.source_id).where(
        or_(DataSource.provider != "google_drive_sa", WorkspaceFolder.status != "access_lost"),
        Document.id == document_id, Document.organization_id == organization_id,
        Document.workspace_folder_id.in_([item.id for item in contexts]),
        readable_document_clause(session, access),  # a scope read in part: only files below a granted folder
    ))
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'evidence not found')
    return document


@router.get('/organizations/{organization_id}/documents/{document_id}/evidence')
def citation_evidence(organization_id: UUID, document_id: UUID, chunk_id: UUID = Query(),
                      user: User = Depends(current_user),
                      session: Session = Depends(database_session)) -> dict[str, object]:
    document = scoped_document(session, organization_id=organization_id, document_id=document_id, user=user)
    chunk = session.scalar(select(DocumentChunk).where(
        DocumentChunk.id == chunk_id, DocumentChunk.document_id == document_id,
        DocumentChunk.organization_id == organization_id,
    ))
    if chunk is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'evidence not found')
    return {
        'document_id': str(document.id),
        'chunk_id': str(chunk.id),
        'document_name': document.name,
        'page_number': chunk.page_number,
        'position': chunk.position,
        'source_url': document.source_url,
        'text': chunk.text[:MAX_PASSAGE_CHARS],
    }
