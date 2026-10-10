"""Living questions: re-ask followed saved queries after a sync that changed their folder."""
import logging
from datetime import UTC, datetime
from difflib import SequenceMatcher
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit_usage.models import SavedQuery
from app.audit_usage.service import UsageLimitExceeded
from app.core.scoping import OrganizationScope
from app.integrations.google_drive import GoogleAccessDenied
from app.knowledge.models import Document
from app.knowledge.questions import (
    AIProviderUnavailable,
    Evidence,
    QuestionService,
    SemanticProvider,
)
from app.notifications.service import NotificationService
from app.organizations.delivery import EmailDeliveryPort

logger = logging.getLogger(__name__)
SIMILARITY_UNCHANGED = 0.92
BODY_CHARS = 600


def citation_payload(citations: list[Evidence]) -> list[dict[str, object]]:
    return [{"document_id": str(item.document_id), "document_name": item.document_name,
             "source_url": item.source_url, "page_number": item.page_number, "excerpt": item.excerpt[:240]}
            for item in citations]


def answer_changed(previous: dict[str, object], text: str, document_ids: list[str]) -> bool:
    if sorted(previous.get("document_ids") or []) != sorted(document_ids):
        return True
    ratio = SequenceMatcher(None, " ".join(str(previous.get("text") or "").split()).casefold(),
                            " ".join(text.split()).casefold()).ratio()
    return ratio < SIMILARITY_UNCHANGED


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _has_changes(session: Session, query: SavedQuery) -> bool:
    since = _aware(query.last_checked_at or query.created_at)
    return session.scalar(select(Document.id).where(
        Document.organization_id == query.organization_id, Document.workspace_folder_id == query.workspace_folder_id,
        Document.index_status == "indexed",
        or_(Document.indexed_at > since, Document.modified_at > since)).limit(1)) is not None


def refresh_followed_queries(session: Session, *, workspace_folder_id: UUID, provider: SemanticProvider,
                             email: EmailDeliveryPort | None = None, app_url: str = "") -> dict[str, int]:
    counts = {"considered": 0, "rerun": 0, "notified": 0}
    queries = list(session.scalars(select(SavedQuery).where(
        SavedQuery.workspace_folder_id == workspace_folder_id, SavedQuery.followed.is_(True))
        .order_by(SavedQuery.created_at, SavedQuery.id)))
    for query in queries:
        counts["considered"] += 1
        if not _has_changes(session, query):
            continue
        scope = OrganizationScope(query.organization_id)
        try:
            with session.begin_nested():
                result = QuestionService(session, provider).ask(
                    scope=scope, user_id=query.user_id, workspace_folder_id=query.workspace_folder_id, question=query.query)
                counts["rerun"] += 1
                checked_at = datetime.now(UTC)
                query.last_checked_at = checked_at
                if result.answer is None:
                    continue
                ids = sorted({str(item.document_id) for item in result.citations})
                snapshot = {"text": result.answer, "document_ids": ids, "at": checked_at.isoformat()}
                previous = query.last_answer
                query.last_answer = snapshot
                if previous is None or not answer_changed(previous, result.answer, ids):
                    continue  # first run only sets the baseline; identical answers stay silent
                NotificationService(session).notify(
                    scope=scope, user_id=query.user_id, kind="followed_query_changed",
                    title=f"A resposta de “{query.name}” mudou",
                    body=result.answer[:BODY_CHARS],
                    data={"saved_query_id": str(query.id), "workspace_folder_id": str(query.workspace_folder_id),
                          "query_name": query.name, "citations": citation_payload(result.citations)},
                    email=email, app_url=app_url)
                counts["notified"] += 1
        except UsageLimitExceeded:
            logger.info("followed queries paused: organization question quota reached")
            break
        except AIProviderUnavailable:
            logger.warning("followed queries paused: AI provider unavailable")
            break
        except (GoogleAccessDenied, ValueError):
            continue
    return counts
