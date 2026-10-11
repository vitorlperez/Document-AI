"""On-click evidence for a citation: the cited passage and where it lives, scoped to what the member may query."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user, database_session
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.ingestion.service import SyncAccessDenied
from app.knowledge.models import Document, DocumentChunk
from app.library.service import LibraryService

router = APIRouter(tags=['evidence'])
MAX_PASSAGE_CHARS = 4000


def scoped_document(session: Session, *, organization_id: UUID, document_id: UUID, user: User) -> Document:
    """The document only when the member may query its folder; 404 otherwise (never reveals existence)."""
    scope = OrganizationScope(organization_id)
    try:
        contexts = LibraryService(session).question_contexts(scope=scope, user_id=user.id)
    except SyncAccessDenied as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'evidence not found') from error
    document = session.scalar(select(Document).where(
        Document.id == document_id, Document.organization_id == organization_id,
        Document.workspace_folder_id.in_([item.id for item in contexts]),
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
