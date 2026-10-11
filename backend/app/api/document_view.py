"""In-chat file viewing: metadata, original bytes (streamed from the connector), Office preview and extracted chunks.

Every route reuses the evidence scope check: a member only reaches documents in folders they may query.
"""
import re
import unicodedata
from collections.abc import Iterator
from typing import IO
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import current_user, database_session
from app.api.evidence import MAX_PASSAGE_CHARS, scoped_document
from app.identity.models import User
from app.integrations.models import DataSource
from app.knowledge.file_access import (
    MICROSOFT_PROVIDERS,
    SERVED_BINARY,
    DocumentFileFetcher,
    FileAccessError,
    servable_content_type,
)
from app.knowledge.models import Document, DocumentChunk
from app.workspaces.models import WorkspaceFolder

router = APIRouter(tags=['document-view'])
STREAM_CHUNK_BYTES = 256 * 1024
DEFAULT_CHUNK_PAGE = 60
MAX_CHUNK_PAGE = 100
_UNSAFE_NAME = re.compile(r'[\x00-\x1f\x7f"\\/:*?<>|;]+')


def safe_filename(name: str) -> str:
    cleaned = _UNSAFE_NAME.sub(' ', unicodedata.normalize('NFC', name)).strip(' .')
    return (cleaned or 'arquivo')[:150]


def content_disposition(name: str) -> str:
    safe = safe_filename(name)
    ascii_name = safe.encode('ascii', 'ignore').decode().strip() or 'arquivo'
    return f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(safe, safe='')}"


def file_fetcher(request: Request, session: Session = Depends(database_session)) -> DocumentFileFetcher:
    override = getattr(request.app.state, 'document_file_fetcher', None)
    return override or DocumentFileFetcher(request.app.state.settings, session)


def _source_of(session: Session, document: Document) -> DataSource:
    source = session.scalar(
        select(DataSource).join(WorkspaceFolder, WorkspaceFolder.source_id == DataSource.id).where(
            WorkspaceFolder.id == document.workspace_folder_id,
            DataSource.organization_id == document.organization_id,
        )
    )
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'evidence not found')
    return source


def _error(error: FileAccessError) -> HTTPException:
    headers = {'Retry-After': str(error.retry_after)} if error.retry_after else None
    return HTTPException(error.status_code, error.code, headers=headers)


def _chunks_of(stream: IO[bytes]) -> Iterator[bytes]:
    try:
        while block := stream.read(STREAM_CHUNK_BYTES):
            yield block
    finally:
        stream.close()


@router.get('/organizations/{organization_id}/documents/{document_id}/view')
def document_view(organization_id: UUID, document_id: UUID, user: User = Depends(current_user),
                  session: Session = Depends(database_session)) -> dict[str, object]:
    document = scoped_document(session, organization_id=organization_id, document_id=document_id, user=user)
    source = _source_of(session, document)
    served = servable_content_type(document, source.provider)
    return {
        'document_id': str(document.id),
        'name': document.name,
        'mime_type': document.mime_type,
        'source_provider': source.provider,
        'source_url': document.source_url,
        'file_available': served is not None,
        'file_content_type': served[0] if served else None,
        'office_preview': source.provider in MICROSOFT_PROVIDERS and document.mime_type in SERVED_BINARY,
    }


@router.get('/organizations/{organization_id}/documents/{document_id}/file')
def document_file(organization_id: UUID, document_id: UUID, user: User = Depends(current_user),
                  session: Session = Depends(database_session),
                  fetcher: DocumentFileFetcher = Depends(file_fetcher)) -> StreamingResponse:
    document = scoped_document(session, organization_id=organization_id, document_id=document_id, user=user)
    source = _source_of(session, document)
    try:
        opened = fetcher.open(document, source)
    except FileAccessError as error:
        raise _error(error) from error
    return StreamingResponse(_chunks_of(opened.stream), media_type=opened.content_type, headers={
        'Content-Length': str(opened.size),
        'Content-Disposition': content_disposition(opened.filename),
        'X-Content-Type-Options': 'nosniff',
        'Cache-Control': 'private, max-age=60',
        'Content-Security-Policy': "default-src 'none'; sandbox",
    })


class PreviewRequest(BaseModel):
    page: int | None = Field(default=None, ge=1, le=10_000)


@router.post('/organizations/{organization_id}/documents/{document_id}/preview')
def document_preview(organization_id: UUID, document_id: UUID, payload: PreviewRequest,
                     user: User = Depends(current_user), session: Session = Depends(database_session),
                     fetcher: DocumentFileFetcher = Depends(file_fetcher)) -> dict[str, object]:
    """Short-lived Office embed URL, generated per open and never stored or logged; null → use /file."""
    document = scoped_document(session, organization_id=organization_id, document_id=document_id, user=user)
    url = fetcher.preview_url(document, _source_of(session, document), payload.page)
    return {'url': url}


@router.get('/organizations/{organization_id}/documents/{document_id}/chunks')
def document_chunks(organization_id: UUID, document_id: UUID, offset: int = Query(0, ge=0),
                    limit: int = Query(DEFAULT_CHUNK_PAGE, ge=1, le=MAX_CHUNK_PAGE),
                    around_chunk_id: UUID | None = Query(None), user: User = Depends(current_user),
                    session: Session = Depends(database_session)) -> dict[str, object]:
    """Extracted text of the document in reading order, paginated; `around_chunk_id` lands on the page holding it."""
    document = scoped_document(session, organization_id=organization_id, document_id=document_id, user=user)
    base = (DocumentChunk.document_id == document_id, DocumentChunk.organization_id == organization_id)
    total = session.scalar(select(func.count()).select_from(DocumentChunk).where(*base)) or 0
    if around_chunk_id is not None:
        target = session.scalar(select(DocumentChunk.position).where(*base, DocumentChunk.id == around_chunk_id))
        if target is not None:
            before = session.scalar(
                select(func.count()).select_from(DocumentChunk).where(*base, DocumentChunk.position < target)
            ) or 0
            offset = before // limit * limit
    rows = session.scalars(
        select(DocumentChunk).where(*base).order_by(DocumentChunk.position).offset(offset).limit(limit)
    ).all()
    return {
        'document_id': str(document.id),
        'document_name': document.name,
        'total': total,
        'offset': offset,
        'limit': limit,
        'has_more': offset + len(rows) < total,
        'chunks': [
            {'id': str(row.id), 'position': row.position, 'page_number': row.page_number, 'text': row.text[:MAX_PASSAGE_CHARS]}
            for row in rows
        ],
    }
