"""In-app notifications, e-mail preference and the on-demand weekly digest."""
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import current_user, database_session
from app.audit_usage.service import UsageLimitExceeded
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.ingestion.service import SyncAccessDenied
from app.knowledge.questions import AIProviderUnavailable
from app.library.service import LibraryService
from app.notifications.digest import build_digest
from app.notifications.models import Notification
from app.notifications.service import NotificationService

router = APIRouter(tags=["notifications"])


class PreferencesInput(BaseModel):
    email_enabled: bool


class MarkReadInput(BaseModel):
    ids: list[UUID] | None = None  # None marks everything read


def _member_scope(session: Session, organization_id: UUID, user: User) -> OrganizationScope:
    scope = OrganizationScope(organization_id)
    try:
        LibraryService(session).require_member(scope=scope, user_id=user.id)
    except SyncAccessDenied as error:
        raise HTTPException(403, "not allowed") from error
    return scope


def _serialize(item: Notification) -> dict[str, object]:
    return {"id": str(item.id), "kind": item.kind, "title": item.title, "body": item.body, "data": item.data,
            "created_at": item.created_at, "read": item.read_at is not None}


@router.get("/organizations/{organization_id}/notifications")
def list_notifications(organization_id: UUID, limit: int = Query(30, ge=1, le=100), user: User = Depends(current_user),
                       session: Session = Depends(database_session)) -> dict[str, object]:
    scope = _member_scope(session, organization_id, user)
    service = NotificationService(session)
    return {"unread": service.unread_count(scope=scope, user_id=user.id),
            "items": [_serialize(item) for item in service.list(scope=scope, user_id=user.id, limit=limit)]}


@router.post("/organizations/{organization_id}/notifications/read")
def mark_notifications_read(organization_id: UUID, payload: MarkReadInput, user: User = Depends(current_user),
                            session: Session = Depends(database_session)) -> dict[str, int]:
    scope = _member_scope(session, organization_id, user)
    service = NotificationService(session)
    if payload.ids is None:
        service.mark_read(scope=scope, user_id=user.id, notification_id=None)
    else:
        for notification_id in payload.ids:
            service.mark_read(scope=scope, user_id=user.id, notification_id=notification_id)
    session.commit()
    return {"unread": service.unread_count(scope=scope, user_id=user.id)}


@router.get("/organizations/{organization_id}/notification-preferences")
def get_preferences(organization_id: UUID, user: User = Depends(current_user),
                    session: Session = Depends(database_session)) -> dict[str, bool]:
    scope = _member_scope(session, organization_id, user)
    return {"email_enabled": NotificationService(session).email_enabled(scope=scope, user_id=user.id)}


@router.put("/organizations/{organization_id}/notification-preferences")
def set_preferences(organization_id: UUID, payload: PreferencesInput, user: User = Depends(current_user),
                    session: Session = Depends(database_session)) -> dict[str, bool]:
    scope = _member_scope(session, organization_id, user)
    value = NotificationService(session).set_email_enabled(scope=scope, user_id=user.id, enabled=payload.email_enabled)
    session.commit()
    return {"email_enabled": value}


@router.post("/organizations/{organization_id}/digest/weekly")
def weekly_digest(organization_id: UUID, request: Request, days: int = Query(7, ge=1, le=31),
                  user: User = Depends(current_user), session: Session = Depends(database_session)) -> dict[str, object]:
    """On-demand "what changed" summary; nothing is stored or e-mailed. Counts against the question quota."""
    scope = _member_scope(session, organization_id, user)
    since = datetime.now(UTC) - timedelta(days=days)
    try:
        sections = build_digest(session, scope=scope, user_id=user.id,
                                provider=request.app.state.semantic_provider, since=since)
    except UsageLimitExceeded as error:
        session.rollback()
        raise HTTPException(429, "organization usage limit reached") from error
    except AIProviderUnavailable as error:
        session.rollback()
        raise HTTPException(503, "AI provider unavailable") from error
    session.commit()
    return {"since": since, "days": days, "sections": sections}
