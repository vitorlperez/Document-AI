"""Admin synchronization and member document-listing HTTP boundaries."""

import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.api.auth import current_user, database_session
from app.audit_usage.service import UsageLimitExceeded
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.ingestion.models import ProcessingJob
from app.ingestion.service import (
    IngestionService,
    ManagedDocumentNotFound,
    SyncAccessDenied,
    SyncAlreadyActive,
)
from app.integrations.google_drive import GoogleAccessDenied
from app.knowledge.questions import AIProviderUnavailable, QuestionResult, QuestionService
from app.knowledge.search import SearchUnavailable, TextSearchService
from app.library.service import LibraryService

router = APIRouter(tags=["ingestion"])
MAX_CITATION_EXCERPT_LENGTH = 240
_MARKDOWN_LINK_START = re.compile(r"\[([^\]]+)\]\(")
_AUTOLINK = re.compile(r"<\s*(?:https?://|www\.)[^>]+>", re.IGNORECASE)
_URL = re.compile(
    r"\b(?:(?:https?://|www\.)[^\s<>]+|(?:drive|docs)\.google\.com/[^\s<>]+|"
    r"(?:[A-Za-z0-9-]+\.)?notion\.(?:so|site)/[^\s<>]+)",
    re.IGNORECASE,
)
_SOURCE_LINK_LINE = re.compile(
    r"\s*(?:[-*]\s*)?(?:(?:fonte|fontes|source|sources|link|links|url)\s*[:\-]|\[\d+\]:)"
    r"[^\n]*(?:https?://|www\.|(?:drive|docs)\.google\.com/|notion\.(?:so|site)/)[^\n]*",
    re.IGNORECASE,
)
_SOURCE_ONLY_LINE = re.compile(
    r"\s*(?:[-*]\s*)?(?:(?:fonte|fontes|source|sources|link|links|url)\s*[:\-]|\[\d+\]:)\s*[.,;:!?()\[\]\s]*",
    re.IGNORECASE,
)
_PROVIDER_URL = re.compile(
    r"\s*\(\s*[a-z][a-z0-9_]{1,40}\s*:\s*(?:https?://|www\.)[^)\n]*\)",
    re.IGNORECASE,
)
_INLINE_CITATION_MARKER = re.compile(r"\[\d+\]")


class TextSearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=50)


class QuestionInput(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    scope: Literal["folder", "provider", "organization"] = "folder"
    provider: str | None = Field(default=None, min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")

    @model_validator(mode="after")
    def validate_scope(self) -> "QuestionInput":
        if self.scope == "provider" and self.provider is None:
            raise ValueError("provider is required")
        if self.scope != "provider" and self.provider is not None:
            raise ValueError("provider is only valid for provider scope")
        if not self.question.strip():
            raise ValueError("question must not be blank")
        return self


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


@router.delete("/workspace-folders/{workspace_folder_id}/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_document_from_index(
    workspace_folder_id: UUID,
    document_id: UUID,
    organization_id: UUID,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> None:
    try:
        scope = OrganizationScope(organization_id)
        removed = IngestionService(session).remove_indexed_document(
            scope=scope, user_id=user.id, workspace_folder_id=workspace_folder_id, document_id=document_id
        )
        LibraryService(session).remove_file_if_unindexed(
            scope=scope, source_id=removed.source_id, external_file_id=removed.external_file_id
        )
        session.commit()
    except SyncAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error
    except ManagedDocumentNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found") from error
    except SyncAlreadyActive as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="workspace sync already active") from error


@router.post(
    "/workspace-folders/{workspace_folder_id}/documents/{document_id}/reprocess",
    status_code=status.HTTP_202_ACCEPTED,
)
def reprocess_document(
    workspace_folder_id: UUID,
    document_id: UUID,
    organization_id: UUID,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, str]:
    try:
        job = IngestionService(session).request_document_reprocess(
            scope=OrganizationScope(organization_id),
            user_id=user.id,
            workspace_folder_id=workspace_folder_id,
            document_id=document_id,
        )
        session.commit()
    except SyncAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error
    except ManagedDocumentNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found") from error
    except SyncAlreadyActive as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="workspace sync already active") from error
    try:
        request.app.state.ingestion_dispatcher.dispatch(job_id=job.id)
    except RuntimeError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="sync queue unavailable") from error
    return {"job_id": str(job.id), "status": job.status.value}


@router.delete("/workspace-folders/{workspace_folder_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_workspace_from_index(
    workspace_folder_id: UUID,
    organization_id: UUID,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> None:
    try:
        scope = OrganizationScope(organization_id)
        removed = IngestionService(session).remove_workspace(
            scope=scope, user_id=user.id, workspace_folder_id=workspace_folder_id
        )
        LibraryService(session).remove_files_if_unindexed(
            scope=scope, source_id=removed.source_id, external_file_ids=removed.external_file_ids
        )
        session.commit()
    except SyncAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error
    except SyncAlreadyActive as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="workspace sync already active") from error


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
    if payload.scope != "folder":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="folder scope is required")
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
    return _serialize_question_result(result, include_provider=False)


@router.post("/organizations/{organization_id}/questions")
def ask_organization_question(
    organization_id: UUID,
    payload: QuestionInput,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, object]:
    if payload.scope == "folder":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="organization scope is required")
    if payload.scope == "provider" and not payload.provider:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="provider is required")
    try:
        result = QuestionService(session, request.app.state.semantic_provider).ask_scope(
            scope=OrganizationScope(organization_id),
            user_id=user.id,
            question=payload.question,
            question_scope=payload.scope,
            provider=payload.provider,
        )
    except GoogleAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error
    except AIProviderUnavailable as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="AI provider unavailable") from error
    except UsageLimitExceeded as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="organization usage limit reached") from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    return _serialize_question_result(result, include_provider=True)


def _serialize_question_result(result: QuestionResult, *, include_provider: bool) -> dict[str, object]:
    citations = []
    for item in result.citations:
        citation = {
            "document_id": str(item.document_id),
            "document_name": item.document_name,
            "excerpt": _short_citation_excerpt(item.excerpt),
            "page_number": item.page_number,
            "source_url": item.source_url,
        }
        if include_provider and item.source_provider:
            citation["source_provider"] = item.source_provider
        citations.append(citation)
    payload: dict[str, object] = {
        "answer": _answer_without_source_links(result.answer),
        "confidence": result.confidence,
        "citations": citations,
        "retrieval_status": result.retrieval_status,
    }
    if result.coverage is not None:
        payload["coverage"] = result.coverage
    return payload


def _short_citation_excerpt(value: str) -> str:
    """Keep displayed quotes concise without shortening evidence sent to the model."""
    excerpt = value.strip()
    if len(excerpt) <= MAX_CITATION_EXCERPT_LENGTH:
        return excerpt
    cutoff = max(
        excerpt.rfind(separator, 0, MAX_CITATION_EXCERPT_LENGTH)
        for separator in (" ", "\n", "\t")
    )
    if cutoff < MAX_CITATION_EXCERPT_LENGTH * 0.65:
        cutoff = MAX_CITATION_EXCERPT_LENGTH - 1
    return f"{excerpt[:cutoff].rstrip()}…"


def _answer_without_source_links(value: str | None) -> str | None:
    """Strip accidental model-generated URLs; source links belong to citations."""
    if value is None:
        return None
    answer = "\n".join(line for line in value.splitlines() if not _SOURCE_LINK_LINE.fullmatch(line))
    answer = _strip_markdown_links(answer)
    answer = _AUTOLINK.sub("", answer)
    answer = _PROVIDER_URL.sub("", answer)
    answer = _URL.sub(_remove_url_preserving_punctuation, answer)
    # Current answers carry validated "fonte N" labels. Raw markers from older
    # providers are still discarded; never guess a document from an unknown index.
    answer = _INLINE_CITATION_MARKER.sub("", answer)
    answer = re.sub(r"\(\s*[a-z][a-z0-9_]{1,40}\s*:\s*\)", "", answer, flags=re.IGNORECASE)
    answer = re.sub(r"\(\s*\)", "", answer)
    answer = re.sub(r"[ \t]+([,.;:!?])", r"\1", answer)
    answer = re.sub(r"[ \t]{2,}", " ", answer)
    answer = "\n".join(line for line in answer.splitlines() if not _SOURCE_ONLY_LINE.fullmatch(line))
    answer = re.sub(r"(?m)^\s*[.,;:!?]+\s*$", "", answer)
    answer = re.sub(r"\n{3,}", "\n\n", answer)
    return answer.strip()


def _strip_markdown_links(value: str) -> str:
    """Retain link labels while consuming balanced URL parentheses."""
    parts: list[str] = []
    cursor = 0
    for match in _MARKDOWN_LINK_START.finditer(value):
        if match.start() < cursor:
            continue
        depth = 1
        end = match.end()
        while end < len(value) and depth:
            if value[end] == "(":
                depth += 1
            elif value[end] == ")":
                depth -= 1
            end += 1
        if depth:
            continue
        parts.extend((value[cursor:match.start()], match.group(1)))
        cursor = end
    parts.append(value[cursor:])
    return "".join(parts)


def _remove_url_preserving_punctuation(match: re.Match[str]) -> str:
    url = match.group()
    suffix = ""
    while url and url[-1] in ".,;:!?":
        suffix = url[-1] + suffix
        url = url[:-1]
    while url.endswith(")") and url.count(")") > url.count("("):
        suffix = ")" + suffix
        url = url[:-1]
    return suffix


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
