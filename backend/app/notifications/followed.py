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
from app.ingestion.service import SyncAccessDenied
from app.integrations.google_drive import GoogleAccessDenied
from app.knowledge.derived_visibility import Provenance, build_index, provenance_of_documents
from app.knowledge.models import Document
from app.knowledge.questions import (
    AIProviderUnavailable,
    Evidence,
    QuestionService,
    SemanticProvider,
)
from app.notifications.service import NotificationService
from app.organizations.delivery import EmailDeliveryPort
from app.spaces.access import SpaceAccess, SpaceAccessResolver

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
    accesses: dict[tuple[UUID, UUID], SpaceAccess | None] = {}
    queries = list(session.scalars(select(SavedQuery).where(
        SavedQuery.workspace_folder_id == workspace_folder_id, SavedQuery.followed.is_(True))
        .order_by(SavedQuery.created_at, SavedQuery.id)))
    for query in queries:
        counts["considered"] += 1
        scope = OrganizationScope(query.organization_id)
        # The owner's CURRENT access decides (ADR-0021 §8.2): no folder, no re-run and no model call.
        access = _owner_access(session, accesses, scope, query.user_id)
        if access is None or query.workspace_folder_id not in access.folder_ids:
            continue
        if not _has_changes(session, query):
            continue
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
                if previous is not None and not _baseline_readable(session, access, previous):
                    previous = None  # the old answer cited something the owner can no longer read: re-baseline silently
                query.last_answer = snapshot
                if previous is None or not answer_changed(previous, result.answer, ids):
                    continue  # first run only sets the baseline; identical answers stay silent
                NotificationService(session).notify(
                    scope=scope, user_id=query.user_id, kind="followed_query_changed",
                    title=f"A resposta de “{query.name}” mudou",
                    body=result.answer[:BODY_CHARS],
                    data={"saved_query_id": str(query.id), "workspace_folder_id": str(query.workspace_folder_id),
                          "query_name": query.name, "citations": citation_payload(result.citations)},
                    provenance=provenance_of_documents(
                        session, query.organization_id, {item.document_id for item in result.citations}),
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


def _owner_access(session: Session, cache: dict, scope: OrganizationScope, user_id: UUID) -> SpaceAccess | None:
    key = (scope.organization_id, user_id)
    if key not in cache:
        try:
            cache[key] = SpaceAccessResolver(session).resolve(scope=scope, user_id=user_id)
        except SyncAccessDenied:
            cache[key] = None
    return cache[key]


def _baseline_readable(session: Session, access: SpaceAccess, snapshot: dict[str, object]) -> bool:
    ids = {UUID(str(item)) for item in snapshot.get("document_ids") or [] if _is_uuid(item)}
    return build_index(session, access, [Provenance(document_ids=frozenset(ids))]).visible(
        Provenance(document_ids=frozenset(ids)))


def _is_uuid(value: object) -> bool:
    try:
        UUID(str(value))
    except ValueError:
        return False
    return True


def clear_followed_state_for_lost_access(session: Session, organization_id: UUID, user_id: UUID) -> int:
    """Unfollow queries whose folder left the owner's access and wipe stale answers; returns rows changed.

    Idempotent: a query already cleared is not touched again."""
    scope = OrganizationScope(organization_id)
    access = _owner_access(session, {}, scope, user_id)
    changed = 0
    for query in session.scalars(select(SavedQuery).where(
            SavedQuery.organization_id == organization_id, SavedQuery.user_id == user_id)):
        outside = access is None or query.workspace_folder_id not in access.folder_ids
        dirty = query.followed or query.last_answer is not None or query.last_checked_at is not None
        stale = (not outside and query.last_answer is not None
                 and not _baseline_readable(session, access, query.last_answer))
        if not ((outside and dirty) or stale):
            continue
        if outside:
            query.followed = False
        query.last_answer = None
        query.last_checked_at = None
        changed += 1
    session.flush()
    return changed
