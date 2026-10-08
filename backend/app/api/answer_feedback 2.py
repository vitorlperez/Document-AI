"""User-owned answer feedback, stored beside assessment metadata without a migration."""
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user, database_session
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.ingestion.service import SyncAccessDenied
from app.knowledge.models import Conversation, ConversationMessage
from app.library.service import LibraryService

router = APIRouter(tags=['answer-feedback'])


class FeedbackInput(BaseModel):
    vote: Literal['up', 'down']


@router.put('/organizations/{organization_id}/conversations/{conversation_id}/messages/{message_id}/feedback')
def answer_feedback(organization_id: UUID, conversation_id: UUID, message_id: UUID,
                    payload: FeedbackInput, user: User = Depends(current_user),
                    session: Session = Depends(database_session)) -> dict:
    try:
        LibraryService(session).require_member(scope=OrganizationScope(organization_id), user_id=user.id)
    except SyncAccessDenied as error:
        raise HTTPException(404, 'answer not found') from error
    # The parent lock also serializes feedback replacement, avoiding lost JSON updates.
    conversation = session.scalar(select(Conversation).where(
        Conversation.id == conversation_id, Conversation.organization_id == organization_id,
        Conversation.user_id == user.id,
    ).with_for_update())
    if conversation is None:
        raise HTTPException(404, 'answer not found')
    message = session.scalar(select(ConversationMessage).where(
        ConversationMessage.id == message_id, ConversationMessage.conversation_id == conversation.id,
        ConversationMessage.role == 'assistant',
    ))
    if message is None:
        raise HTTPException(404, 'answer not found')
    feedback = {'vote': payload.vote, 'updated_at': datetime.now(UTC).isoformat()}
    message.context = {**(message.context or {}), 'feedback': feedback}
    session.commit()
    return {'message_id': str(message.id), **feedback}
