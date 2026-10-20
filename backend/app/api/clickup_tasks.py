"""Create a ClickUp task from one of the user's own stored answers (ADR-0020).

A human action over REST: it is deliberately not an agent tool and not an MCP tool.
"""
import re
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user, database_session
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.ingestion.service import SyncAccessDenied
from app.integrations.clickup import ClickUpOAuthClient
from app.integrations.clickup_tasks import (
    ClickUpTaskError,
    ClickUpTaskService,
    TaskInput,
    authorship_footer,
    draft_description,
    suggested_title,
)
from app.integrations.google_drive import CredentialCipher
from app.knowledge.derived_visibility import message_is_visible
from app.knowledge.models import Conversation, ConversationMessage
from app.library.service import LibraryService

router = APIRouter(tags=['clickup-tasks'])
BASE = '/organizations/{organization_id}/conversations/{conversation_id}/messages/{message_id}/clickup-task'
_RAW_ID = re.compile(r'^[A-Za-z0-9_-]{1,64}$')


class CreateTaskInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    list_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=1000)
    description: str = Field(default='', max_length=100_000)
    assignees: list[int] = Field(default_factory=list, max_length=50)
    due_date: date | None = None
    priority: int | None = Field(default=None, ge=1, le=4)
    tags: list[str] = Field(default_factory=list, max_length=50)


def _service(request: Request, session: Session) -> ClickUpTaskService:
    settings = request.app.state.settings
    keys = settings.cipher_keys('clickup')
    client = getattr(request.app.state, 'clickup_client', None) or ClickUpOAuthClient(
        client_id=settings.clickup_oauth_client_id,
        client_secret=settings.clickup_oauth_client_secret.get_secret_value() if settings.clickup_oauth_client_secret else None,
        redirect_uri=settings.clickup_oauth_redirect_uri,
    )
    return ClickUpTaskService(session, client, CredentialCipher(keys[0], fallback_keys=keys[1:]))


def _refuse(error: ClickUpTaskError) -> HTTPException:
    headers = {'Retry-After': str(error.retry_after)} if error.retry_after else None
    return HTTPException(error.status, error.message, headers=headers)


def _own_answer(session: Session, organization_id: UUID, conversation_id: UUID, message_id: UUID,
                user: User) -> ConversationMessage:
    try:
        LibraryService(session).require_member(scope=OrganizationScope(organization_id), user_id=user.id)
    except SyncAccessDenied as error:
        raise HTTPException(404, 'answer not found') from error
    conversation = session.scalar(select(Conversation).where(
        Conversation.id == conversation_id, Conversation.organization_id == organization_id,
        Conversation.user_id == user.id,
    ))
    message = conversation and session.scalar(select(ConversationMessage).where(
        ConversationMessage.id == message_id, ConversationMessage.conversation_id == conversation.id,
        ConversationMessage.role == 'assistant',
    ))
    if message is None or not message_is_visible(session, organization_id, user.id, message):
        raise HTTPException(404, 'answer not found')
    return message


def _citations(message: ConversationMessage) -> list[dict]:
    items = message.response.get('citations') if isinstance(message.response, dict) else None
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


@router.get(BASE + '/preview')
def preview(organization_id: UUID, conversation_id: UUID, message_id: UUID, request: Request,
            user: User = Depends(current_user), session: Session = Depends(database_session)) -> dict[str, object]:
    """Draft only: reads local data, writes nothing and never calls ClickUp."""
    message = _own_answer(session, organization_id, conversation_id, message_id, user)
    service = _service(request, session)
    try:
        source = service.source(organization_id)
        lists = service.selected_lists(source)
        citations = _citations(message)
        suggested = service.suggest_list(source, lists, citations)
    except ClickUpTaskError as error:
        raise _refuse(error) from error
    question = session.scalar(select(ConversationMessage.content).where(
        ConversationMessage.conversation_id == message.conversation_id, ConversationMessage.role == 'user',
        ConversationMessage.position < message.position,
    ).order_by(ConversationMessage.position.desc()).limit(1))
    return {
        'lists': [{'id': item.id, 'name': item.name, 'path': item.path} for item in lists],
        'suggested_list_id': suggested,
        'name': suggested_title(question),
        'description': draft_description(message.content, citations),
        'footer': authorship_footer(user.email),
    }


@router.get(BASE + '/lists/{list_id}/options')
def list_options(organization_id: UUID, conversation_id: UUID, message_id: UUID, list_id: str, request: Request,
                 user: User = Depends(current_user), session: Session = Depends(database_session)) -> dict[str, object]:
    """Members and statuses of one selected list (one ClickUp read each, on explicit user choice)."""
    _own_answer(session, organization_id, conversation_id, message_id, user)
    if not _RAW_ID.match(list_id):
        raise HTTPException(422, 'Lista inválida.')
    service = _service(request, session)
    try:
        return service.list_options(service.source(organization_id), list_id)
    except ClickUpTaskError as error:
        raise _refuse(error) from error


@router.post(BASE)
def create_task(organization_id: UUID, conversation_id: UUID, message_id: UUID, body: CreateTaskInput,
                request: Request, response: Response, idempotency_key: Annotated[str, Header(alias='Idempotency-Key')],
                user: User = Depends(current_user), session: Session = Depends(database_session)) -> dict[str, object]:
    message = _own_answer(session, organization_id, conversation_id, message_id, user)
    service = _service(request, session)
    try:
        record = service.create(
            organization_id=organization_id, message=message, user_id=user.id, user_email=user.email,
            idempotency_key=idempotency_key,
            task=TaskInput(body.list_id, body.name, body.description, tuple(body.assignees), body.due_date,
                           body.priority, tuple(body.tags)))
    except ClickUpTaskError as error:
        raise _refuse(error) from error
    return {'task_id': record.task_id, 'url': record.task_url, 'status': record.status}
