"""Weekly "what changed" digest: per folder, a cited summary of the documents touched in the window."""
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit_usage.service import UsageLimitExceeded
from app.core.scoping import OrganizationScope
from app.integrations.google_drive import GoogleAccessDenied
from app.knowledge.models import Document
from app.knowledge.questions import AIProviderUnavailable, QuestionService, SemanticProvider
from app.notifications.followed import BODY_CHARS, citation_payload
from app.notifications.models import Notification
from app.notifications.service import NotificationService
from app.organizations.delivery import EmailDeliveryPort
from app.organizations.models import Membership, MembershipRole
from app.workspaces.models import WorkspaceFolder

logger = logging.getLogger(__name__)
DIGEST_QUESTION = "Resuma o que mudou nestes documentos."
MAX_DOCUMENTS_PER_FOLDER = 20
DIGEST_KIND = "weekly_digest"


def build_digest(session: Session, *, scope: OrganizationScope, user_id: UUID, provider: SemanticProvider,
                 since: datetime) -> list[dict[str, object]]:
    """Cited summary sections for every folder with documents modified or indexed since ``since``."""
    sections: list[dict[str, object]] = []
    folders = session.scalars(select(WorkspaceFolder).where(WorkspaceFolder.organization_id == scope.organization_id)
                              .order_by(WorkspaceFolder.name, WorkspaceFolder.id))
    for folder in folders:
        changed = list(session.scalars(select(Document.id).where(
            Document.organization_id == scope.organization_id, Document.workspace_folder_id == folder.id,
            Document.index_status == "indexed", or_(Document.indexed_at >= since, Document.modified_at >= since))
            .order_by(Document.modified_at.desc().nulls_last(), Document.id).limit(MAX_DOCUMENTS_PER_FOLDER)))
        if not changed:
            continue
        try:
            with session.begin_nested():
                result = QuestionService(session, provider).ask(
                    scope=scope, user_id=user_id, workspace_folder_id=folder.id, document_ids=set(changed),
                    question=DIGEST_QUESTION, answer_mode="summary")
        except (UsageLimitExceeded, AIProviderUnavailable):
            raise
        except (GoogleAccessDenied, ValueError):
            continue
        if result.answer:
            sections.append({"workspace_folder_id": str(folder.id), "name": folder.name, "changed_documents": len(changed),
                             "summary": result.answer, "citations": citation_payload(result.citations)})
    return sections


def digest_text(sections: list[dict[str, object]]) -> str:
    return "\n\n".join(f"{item['name']}: {str(item['summary'])[:BODY_CHARS]}" for item in sections)


def send_weekly_digests(session: Session, *, provider: SemanticProvider, email: EmailDeliveryPort | None,
                        app_url: str = "", now: datetime | None = None, days: int = 7) -> dict[str, int]:
    """Notify members of every organization whose folders changed during the last ``days``."""
    current = now or datetime.now(UTC)
    since = current - timedelta(days=days)
    counts = {"organizations": 0, "notified": 0}
    organization_ids = list(session.scalars(select(WorkspaceFolder.organization_id).distinct()))
    for organization_id in organization_ids:
        if session.scalar(select(Notification.id).where(
                Notification.organization_id == organization_id, Notification.kind == DIGEST_KIND,
                Notification.created_at > current - timedelta(days=days - 1)).limit(1)) is not None:
            continue  # already delivered this week (task re-delivery or manual rerun)
        members = list(session.scalars(select(Membership).where(
            Membership.organization_id == organization_id, Membership.is_active.is_(True))
            .order_by(Membership.role, Membership.id)))
        if not members:
            continue
        actor = next((m for m in members if m.role in (MembershipRole.OWNER, MembershipRole.ADMIN)), members[0])
        scope = OrganizationScope(organization_id)
        try:
            sections = build_digest(session, scope=scope, user_id=actor.user_id, provider=provider, since=since)
        except (UsageLimitExceeded, AIProviderUnavailable):
            session.rollback()
            logger.info("weekly digest skipped for organization: quota or provider unavailable")
            continue
        counts["organizations"] += 1
        if not sections:
            continue  # nothing changed: nothing to send
        title = "O que mudou esta semana"
        for member in members:
            NotificationService(session).notify(
                scope=scope, user_id=member.user_id, kind=DIGEST_KIND, title=title, body=digest_text(sections),
                data={"since": since.isoformat(), "sections": sections}, email=email, app_url=app_url)
            counts["notified"] += 1
        session.commit()
    return counts
