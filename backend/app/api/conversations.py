"""Conversation history: the current user's own list, rename and delete (organization scoped)."""
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.auth import current_user, database_session
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.ingestion.service import SyncAccessDenied
from app.knowledge.models import Conversation
from app.library.service import LibraryService

router = APIRouter(tags=['conversations'])


class RenameInput(BaseModel):
    title: str

    @field_validator('title')
    @classmethod
    def _clean(cls, value: str) -> str:
        value = ' '.join(value.split())
        if not 1 <= len(value) <= 160:
            raise ValueError('title must have 1-160 characters')
        return value


def _member(session: Session, organization_id: UUID, user: User) -> None:
    try:
        LibraryService(session).require_member(scope=OrganizationScope(organization_id), user_id=user.id)
    except SyncAccessDenied as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'conversation not found') from error


def _owned(session: Session, organization_id: UUID, conversation_id: UUID, user: User) -> Conversation:
    _member(session, organization_id, user)
    conversation = session.scalar(select(Conversation).where(
        Conversation.id == conversation_id, Conversation.organization_id == organization_id,
        Conversation.user_id == user.id,
    ))
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'conversation not found')
    return conversation


def _item(conversation: Conversation) -> dict[str, object]:
    last: datetime = conversation.last_message_at
    return {
        'id': str(conversation.id),
        'title': conversation.title or 'Nova conversa',
        'last_message_at': last.isoformat(),
        'created_at': conversation.created_at.isoformat(),
    }


@router.get('/organizations/{organization_id}/conversations')
def list_conversations(organization_id: UUID, page: int = Query(1, ge=1, le=10_000),
                       page_size: int = Query(30, ge=1, le=100), user: User = Depends(current_user),
                       session: Session = Depends(database_session)) -> dict[str, object]:
    _member(session, organization_id, user)
    where = (Conversation.organization_id == organization_id, Conversation.user_id == user.id)
    total = int(session.scalar(select(func.count()).select_from(Conversation).where(*where)) or 0)
    rows = session.scalars(select(Conversation).where(*where)
                           .order_by(Conversation.last_message_at.desc(), Conversation.id)
                           .offset((page - 1) * page_size).limit(page_size))
    return {'items': [_item(row) for row in rows], 'page': page, 'page_size': page_size, 'total': total}


@router.patch('/organizations/{organization_id}/conversations/{conversation_id}')
def rename_conversation(organization_id: UUID, conversation_id: UUID, payload: RenameInput,
                        user: User = Depends(current_user),
                        session: Session = Depends(database_session)) -> dict[str, object]:
    conversation = _owned(session, organization_id, conversation_id, user)
    conversation.title = payload.title
    session.commit()
    return _item(conversation)


@router.delete('/organizations/{organization_id}/conversations/{conversation_id}',
               status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(organization_id: UUID, conversation_id: UUID, user: User = Depends(current_user),
                        session: Session = Depends(database_session)) -> Response:
    conversation = _owned(session, organization_id, conversation_id, user)
    session.execute(delete(Conversation).where(Conversation.id == conversation.id))
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
