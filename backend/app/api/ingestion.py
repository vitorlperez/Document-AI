"""Admin synchronization and member document-listing HTTP boundaries."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.auth import current_user, database_session
from app.audit_usage.service import UsageLimitExceeded
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.ingestion.models import ProcessingJob
from app.ingestion.service import IngestionService, SyncAccessDenied
from app.integrations.google_drive import GoogleAccessDenied
from app.knowledge.questions import AIProviderUnavailable, QuestionService
from app.knowledge.search import SearchUnavailable, TextSearchService

router = APIRouter(tags=["ingestion"])


class TextSearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=50)


class QuestionInput(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


@router.post("/workspace-folders/{workspace_folder_id}/sync", status_code=status.HTTP_202_ACCEPTED)
def enqueue_sync(
    workspace_folder_id: UUID,
    organization_id: UUID,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, str]:
    try:
        job = IngestionService(session).enqueue(
            scope=OrganizationScope(organization_id), user_id=user.id, workspace_folder_id=workspace_folder_id
        )
    except SyncAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error

    # Commit the durable job before handing it to a worker so an eager worker can
    # never observe an uncommitted row. A dispatch failure leaves an observable
    # queued job that an Admin can safely retry.
    session.commit()
    try:
        request.app.state.ingestion_dispatcher.dispatch(job_id=job.id)
    except RuntimeError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="sync queue unavailable") from error
    return {"job_id": str(job.id), "status": job.status.value}


@router.get("/workspace-folders/{workspace_folder_id}/documents")
def documents(
    workspace_folder_id: UUID,
    organization_id: UUID,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> list[dict[str, str | None]]:
    try:
        rows = IngestionService(session).indexed_documents(
            scope=OrganizationScope(organization_id), user_id=user.id, workspace_folder_id=workspace_folder_id
        )
    except SyncAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error
    return [
        {
            "id": str(row.id),
            "name": row.name,
            "source_url": row.source_url,
            "modified_at": row.modified_at.isoformat() if row.modified_at else None,
        }
        for row in rows
    ]


@router.get("/workspace-folders/{workspace_folder_id}/documents/failures")
def document_failures(
    workspace_folder_id: UUID,
    organization_id: UUID,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> list[dict[str, str | None]]:
    try:
        rows = IngestionService(session).nonindexed_documents(
            scope=OrganizationScope(organization_id), user_id=user.id, workspace_folder_id=workspace_folder_id
        )
    except SyncAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error
    return [
        {
            "id": str(row.id),
            "name": row.name,
            "status": row.index_status,
            "error_code": row.error_code,
            "source_url": row.source_url,
        }
        for row in rows
    ]


@router.post("/workspace-folders/{workspace_folder_id}/search")
def text_search(
    workspace_folder_id: UUID,
    organization_id: UUID,
    payload: TextSearchInput,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, object]:
    try:
        results = TextSearchService(session).search(
            scope=OrganizationScope(organization_id),
            user_id=user.id,
            workspace_folder_id=workspace_folder_id,
            query=payload.query,
            page=payload.page,
            page_size=payload.page_size,
        )
    except GoogleAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error
    except SearchUnavailable as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="folder is not ready") from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    return {
        "items": [
            {
                "document_id": str(item.document_id),
                "document_name": item.document_name,
                "excerpt": item.excerpt,
                "page_number": item.page_number,
                "source_url": item.source_url,
            }
            for item in results.items
        ],
        "page": results.page,
        "page_size": results.page_size,
        "total": results.total,
        "pages": results.pages,
    }


@router.post("/workspace-folders/{workspace_folder_id}/questions")
def ask_question(
    workspace_folder_id: UUID,
    organization_id: UUID,
    payload: QuestionInput,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, object]:
    try:
        result = QuestionService(session, request.app.state.semantic_provider).ask(
            scope=OrganizationScope(organization_id),
            user_id=user.id,
            workspace_folder_id=workspace_folder_id,
            question=payload.question,
        )
    except GoogleAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error
    except AIProviderUnavailable as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="AI provider unavailable") from error
    except UsageLimitExceeded as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="organization usage limit reached") from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return {
        "answer": result.answer,
        "confidence": result.confidence,
        "citations": [
            {
                "document_id": str(item.document_id),
                "document_name": item.document_name,
                "excerpt": item.excerpt,
                "page_number": item.page_number,
                "source_url": item.source_url,
            }
            for item in result.citations
        ],
        "retrieval_status": result.retrieval_status,
    }


@router.get("/workspace-folders/{workspace_folder_id}/syncs/{job_id}")
def sync_status(
    workspace_folder_id: UUID,
    job_id: UUID,
    organization_id: UUID,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, str | None]:
    service = IngestionService(session)
    try:
        service.require_admin(scope=OrganizationScope(organization_id), user_id=user.id)
        service.require_folder(scope=OrganizationScope(organization_id), workspace_folder_id=workspace_folder_id)
    except SyncAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error
    job = session.get(ProcessingJob, job_id)
    if job is None or job.organization_id != organization_id or job.workspace_folder_id != workspace_folder_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="sync not found")
    return {
        "id": str(job.id),
        "status": job.status.value,
        "error_code": job.error_code,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }
