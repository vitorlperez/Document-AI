"""Download one of the user's own assistant answers as Markdown, DOCX or PDF, with its sources."""
import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user, database_session
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.ingestion.service import SyncAccessDenied
from app.knowledge.export import FORMATS, ExportSource, render
from app.knowledge.models import Conversation, ConversationMessage
from app.knowledge.untrusted import sanitize_label
from app.library.service import LibraryService

router = APIRouter(tags=['answer-export'])


def _sources(response: object) -> list[ExportSource]:
    citations = response.get('citations') if isinstance(response, dict) else None
    sources = []
    for item in citations if isinstance(citations, list) else []:
        if isinstance(item, dict) and isinstance(item.get('document_name'), str):
            url = item.get('source_url')
            sources.append(ExportSource(
                sanitize_label(item['document_name']),
                url if isinstance(url, str) and url.startswith(('http://', 'https://')) else '',
            ))
    return sources


@router.get('/organizations/{organization_id}/conversations/{conversation_id}/messages/{message_id}/export')
def export_answer(organization_id: UUID, conversation_id: UUID, message_id: UUID,
                  format: Literal['md', 'docx', 'pdf'] = 'md', user: User = Depends(current_user),
                  session: Session = Depends(database_session)) -> Response:
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
    if message is None:
        raise HTTPException(404, 'answer not found')
    question = session.scalar(select(ConversationMessage.content).where(
        ConversationMessage.conversation_id == conversation.id, ConversationMessage.role == 'user',
        ConversationMessage.position < message.position,
    ).order_by(ConversationMessage.position.desc()).limit(1)) or 'Resposta'
    body, media_type = render(format, title=question, answer=message.content, sources=_sources(message.response))
    slug = re.sub(r'[^A-Za-z0-9]+', '-', question).strip('-')[:40].lower() or 'resposta'
    return Response(body, media_type=media_type, headers={
        'Content-Disposition': f'attachment; filename="arquivio-{slug}.{FORMATS[format][1]}"',
        'Cache-Control': 'no-store',
    })
