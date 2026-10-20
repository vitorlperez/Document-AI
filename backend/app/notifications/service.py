"""Notification persistence, preferences and optional e-mail fan-out."""
import html
import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.knowledge.derived_visibility import Provenance
from app.notifications.automation_email import EmailContent
from app.notifications.models import Notification, NotificationPreference
from app.organizations.delivery import EmailDeliveryPort

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, session: Session):
        self.session = session

    def email_enabled(self, *, scope: OrganizationScope, user_id: UUID) -> bool:
        preference = self.session.scalar(select(NotificationPreference).where(
            NotificationPreference.organization_id == scope.organization_id, NotificationPreference.user_id == user_id))
        return True if preference is None else preference.email_enabled

    def set_email_enabled(self, *, scope: OrganizationScope, user_id: UUID, enabled: bool) -> bool:
        preference = self.session.scalar(select(NotificationPreference).where(
            NotificationPreference.organization_id == scope.organization_id, NotificationPreference.user_id == user_id))
        if preference is None:
            preference = NotificationPreference(organization_id=scope.organization_id, user_id=user_id, email_enabled=enabled)
            self.session.add(preference)
        else:
            preference.email_enabled = enabled
        self.session.flush()
        return preference.email_enabled

    def notify(self, *, scope: OrganizationScope, user_id: UUID, kind: str, title: str, body: str,
               data: dict[str, object], email: EmailDeliveryPort | None = None, app_url: str = "",
               email_content: EmailContent | None = None, provenance: Provenance | None = None) -> Notification:
        """Persist the in-app notification; e-mail it too when the member has not opted out.

        ``provenance`` (documents/folders the content came from) is stored in ``data`` so the bell can hide the
        item once the person loses access to any of them (ADR-0021 §8.2)."""
        if provenance:
            data = {**data, "provenance": provenance.to_data()}
        notification = Notification(organization_id=scope.organization_id, user_id=user_id, kind=kind,
                                    title=title[:200], body=body, data=data)
        self.session.add(notification)
        self.session.flush()
        if email is not None and self.email_enabled(scope=scope, user_id=user_id):
            address = self.session.scalar(select(User.email).where(User.id == user_id))
            if address:
                try:
                    if email_content is not None:
                        email.send_email(recipient=address, subject=title, html=email_content.html, text=email_content.text)
                    else:
                        email.send_email(recipient=address, subject=title, html=render_email(title, body, data, app_url))
                except Exception:
                    logger.exception("notification e-mail failed")
        return notification

    def list(self, *, scope: OrganizationScope, user_id: UUID, limit: int = 30) -> list[Notification]:
        return list(self.session.scalars(select(Notification).where(
            Notification.organization_id == scope.organization_id, Notification.user_id == user_id)
            .order_by(Notification.created_at.desc(), Notification.id).limit(limit)))

    def unread_count(self, *, scope: OrganizationScope, user_id: UUID) -> int:
        return self.session.scalar(select(func.count()).select_from(Notification).where(
            Notification.organization_id == scope.organization_id, Notification.user_id == user_id,
            Notification.read_at.is_(None))) or 0

    def mark_read(self, *, scope: OrganizationScope, user_id: UUID, notification_id: UUID | None) -> int:
        """Mark one notification (or all when ``notification_id`` is None) read; returns rows touched."""
        statement = update(Notification).where(
            Notification.organization_id == scope.organization_id, Notification.user_id == user_id,
            Notification.read_at.is_(None)).values(read_at=datetime.now(UTC))
        if notification_id is not None:
            statement = statement.where(Notification.id == notification_id)
        return self.session.execute(statement).rowcount or 0


def render_email(title: str, body: str, data: dict[str, object], app_url: str) -> str:
    citations = data.get("citations") if isinstance(data.get("citations"), list) else []
    items = "".join(
        f'<li><a href="{html.escape(str(c.get("source_url") or "#"))}">{html.escape(str(c.get("document_name") or "Documento"))}</a></li>'
        for c in citations if isinstance(c, dict))
    link = f'<p><a href="{html.escape(app_url)}">Abrir o Arquivio</a></p>' if app_url else ""
    return (f"<h2>{html.escape(title)}</h2><p>{html.escape(body).replace(chr(10), '<br>')}</p>"
            f"{'<p>Fontes:</p><ul>' + items + '</ul>' if items else ''}{link}")
