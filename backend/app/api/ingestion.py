"""Admin synchronization and member document-listing HTTP boundaries."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
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
from app.knowledge.agent import (
    ConversationService,
    agent_service_from_settings,
)
from app.knowledge.models import ConversationMessage
from app.knowledge.presentation import (
    answer_without_source_links as _answer_without_source_links,  # noqa: F401 — compatibility alias
)
from app.knowledge.presentation import (
    serialize_question_result as _serialize_question_result,
)
from app.knowledge.presentation import (
    short_citation_excerpt as _short_citation_excerpt,  # noqa: F401 — compatibility alias
)
from app.knowledge.questions import AIProviderUnavailable, QuestionService
from app.knowledge.search import SearchUnavailable, TextSearchService
from app.library.service import LibraryService
from app.library.tool_groups import tool_group
from app.organizations.models import Membership
from app.spaces.access import SpaceAccessResolver
from app.spaces.service import SpaceNotFound

router = APIRouter(tags=["ingestion"])
DOCUMENTS_PAGE_SIZE_MAX = 500


def _folder_readable(session: Session, organization_id: UUID, user_id: UUID, workspace_folder_id: UUID) -> bool:
    """Whether the folder is in the caller's Spaces (ADR-0021). Not an active member -> SyncAccessDenied."""
    access = SpaceAccessResolver(session).resolve(scope=OrganizationScope(organization_id), user_id=user_id)
    return access.allows(workspace_folder_id)


def _folder_denied(session: Session, organization_id: UUID, user_id: UUID) -> HTTPException:
    """People outside the organization stay 403; members who cannot reach the folder get a uniform 404 (I7)."""
    member = session.scalar(select(Membership.id).where(
        Membership.organization_id == organization_id, Membership.user_id == user_id,
        Membership.is_active.is_(True)))
    if member is None:
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed")
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workspace not found")


class TextSearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=50)


class QuestionMention(BaseModel):
    kind: Literal["file", "folder"]
    node_id: UUID
    name: str | None = Field(default=None, max_length=300)


SELECTABLE_PROVIDERS = frozenset({"google_drive", "google_drive_sa", "notion", "onedrive", "clickup"})


class QuestionInput(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    scope: Literal["folder", "provider", "organization", "selection"] = "folder"
    provider: str | None = Field(default=None, min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")
    providers: list[str] | None = None
    mentions: list[QuestionMention] | None = None
    conversation_id: UUID | None = None
    # Optional narrowing to some of the caller's Spaces (ADR-0021 D4); an empty list means "no filter".
    space_ids: list[UUID] | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def validate_scope(self) -> "QuestionInput":
        if not self.space_ids:
            self.space_ids = None
        if self.scope == "provider" and self.provider is None:
            raise ValueError("provider is required")
        if self.scope != "provider" and self.provider is not None:
            raise ValueError("provider is only valid for provider scope")
        if self.scope == "selection":
            if not self.providers or len(self.providers) > len(SELECTABLE_PROVIDERS):
                raise ValueError("selection requires one or more providers")
            normalized = [tool_group(item) for item in self.providers]
            if any(item not in SELECTABLE_PROVIDERS for item in normalized):
                raise ValueError("provider is invalid")
            if len(set(normalized)) != len(normalized):
                raise ValueError("providers must be distinct")
            self.providers = normalized
            if self.mentions is not None and (
                len(self.mentions) > 20 or len({item.node_id for item in self.mentions}) != len(self.mentions)
            ):
                raise ValueError("mentions must contain at most 20 distinct nodes")
        elif self.providers is not None or self.mentions is not None:
            raise ValueError("providers and mentions are only valid for selection scope")
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
    response: Response,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=DOCUMENTS_PAGE_SIZE_MAX, ge=1, le=DOCUMENTS_PAGE_SIZE_MAX),
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> list[dict[str, str | None]] | dict[str, object]:
    """Indexed documents of one scope, ``page_size`` at a time (``X-Total-Count`` carries the total)."""
    scope = OrganizationScope(organization_id)
    try:
        if not _folder_readable(session, organization_id, user.id, workspace_folder_id):
            # Not a reader: an org admin gets operational counts without file names; anyone else, 404 (I7).
            try:
                counts = IngestionService(session).document_counts(
                    scope=scope, user_id=user.id, workspace_folder_id=workspace_folder_id
                )
            except SyncAccessDenied as error:
                raise _folder_denied(session, organization_id, user.id) from error
            return {
                "readable": False, "counts": counts,
                "items": [],  # file names are withheld until the admin enters the Space
            }
        ingestion = IngestionService(session)
        ingestion.require_active_member(scope=scope, user_id=user.id)
        ingestion.require_folder(scope=scope, workspace_folder_id=workspace_folder_id)
        rows, total = LibraryService(session).indexed_documents_page(
            scope=scope, workspace_folder_id=workspace_folder_id, page=page, page_size=page_size)
    except SyncAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error
    response.headers["X-Total-Count"] = str(total)
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
        readable = _folder_readable(session, organization_id, user.id, workspace_folder_id)
    except SyncAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error
    # An admin who is not in the folder's Space still operates on failures, but never learns file names.
    return [
        {
            "id": str(row.id),
            "name": row.name if readable else f"arquivo #{str(row.id)[:7]}",
            "status": row.index_status,
            "error_code": row.error_code,
            "source_url": row.source_url if readable else None,
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
        raise _folder_denied(session, organization_id, user.id) from error
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
        raise _folder_denied(session, organization_id, user.id) from error
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
        scope = OrganizationScope(organization_id)
        if payload.space_ids:
            # A Space that is not the caller's does not exist for them: uniform 404 before anything runs.
            SpaceAccessResolver(session).resolve(
                scope=scope, user_id=user.id, space_ids=payload.space_ids, strict=True
            )
        service = QuestionService(session, request.app.state.semantic_provider)
        conversation_service = ConversationService(session)
        conversation, history = conversation_service.create_or_load(
            scope=scope, user_id=user.id, conversation_id=payload.conversation_id, question=payload.question
        )
        request_context = {
            "scope": payload.scope,
            "provider": payload.provider,
            "providers": payload.providers or [],
            "mentions": [
                {"kind": item.kind, "node_id": str(item.node_id), **({"name": item.name} if item.name else {})}
                for item in payload.mentions or []
            ],
            "space_ids": [str(item) for item in payload.space_ids or []],
        }
        conversation_service.append(
            conversation=conversation, role="user", content=payload.question, context=request_context
        )
        if payload.scope == "selection":
            mentions = [(item.kind, item.node_id) for item in payload.mentions or []]
            if request.app.state.settings.agent_tools_enabled:
                result, tool_results, references = agent_service_from_settings(
                    session, request.app.state.semantic_provider, request.app.state.settings,
                ).ask(
                    scope=scope,
                    user_id=user.id,
                    question=payload.question,
                    providers=payload.providers or [],
                    mentions=mentions,
                    history=history,
                    space_ids=payload.space_ids,
                )
            else:
                result = service.ask_selection(
                    scope=scope, user_id=user.id, question=payload.question,
                    providers=payload.providers or [], mentions=mentions, space_ids=payload.space_ids,
                )
                tool_results = []
                references = []
        else:
            result = service.ask_scope(
                scope=scope, user_id=user.id,
                question=payload.question, question_scope=payload.scope, provider=payload.provider,
                space_ids=payload.space_ids,
            )
            tool_results = []
            references = []
        serialized = _serialize_question_result(result, include_provider=True)
        conversation_service.append(
            conversation=conversation,
            role="assistant",
            content=result.answer or "",
            context={
                "resolved_context": result.resolved_context,
                "tool_results": tool_results,
                "references": references,
            },
            response=serialized,
        )
        conversation.last_message_at = datetime.now(UTC)
        session.commit()
    except SpaceNotFound as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="space not found") from error
    except (GoogleAccessDenied, SyncAccessDenied) as error:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not allowed") from error
    except AIProviderUnavailable as error:
        # The question quota is recorded before the provider call. Commit that
        # auditable attempt even when the provider cannot answer.
        session.commit()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="AI provider unavailable") from error
    except UsageLimitExceeded as error:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="organization usage limit reached") from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    response = _serialize_question_result(result, include_provider=True)
    response["conversation_id"] = str(conversation.id)
    return response


@router.get("/organizations/{organization_id}/conversations/{conversation_id}")
def get_conversation(
    organization_id: UUID,
    conversation_id: UUID,
    user: User = Depends(current_user),
    session: Session = Depends(database_session),
) -> dict[str, object]:
    try:
        conversation, messages = ConversationService(session).history(
            scope=OrganizationScope(organization_id), user_id=user.id, conversation_id=conversation_id
        )
    except SyncAccessDenied as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found") from error
    return {
        "id": str(conversation.id),
        "messages": [_serialize_conversation_message(message) for message in messages],
    }


def _serialize_conversation_message(message: ConversationMessage) -> dict[str, object]:
    return {
        "id": str(message.id),
        "role": message.role,
        "content": message.content,
        "context": message.context,
        "response": message.response,
        "created_at": message.created_at.isoformat(),
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
