"""Run creation (idempotent per ``trigger_ref``) for the schedule tick and the post-sync hook."""
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.automations.models import Automation, AutomationRun
from app.automations.schedule import aware, compute_next_run
from app.automations.scope import changed_document_ids, legacy_folder_ids, scope_node_ids
from app.core.scoping import OrganizationScope
from app.knowledge.models import Document
from app.workspaces.models import WorkspaceFolder

logger = logging.getLogger(__name__)
RUN_TASK = "document_intelligence.ingestion.run_automation"


def queue_run(session: Session, automation: Automation, trigger_ref: str) -> AutomationRun | None:
    """Insert a queued run; ``None`` when this trigger already produced one (idempotency)."""
    run = AutomationRun(automation_id=automation.id, organization_id=automation.organization_id,
                        trigger_ref=trigger_ref[:160], status="queued")
    try:
        with session.begin_nested():
            session.add(run)
            session.flush()
    except IntegrityError:
        return None
    return run


def enqueue_due_schedules(session: Session, *, send_task: Callable[..., object], now: datetime | None = None) -> dict[str, int]:
    """Beat tick: queue one run per schedule automation whose ``next_run_at`` has passed."""
    current = now or datetime.now(UTC)
    counts = {"due": 0, "queued": 0}
    due = list(session.scalars(select(Automation).where(
        Automation.enabled.is_(True), Automation.trigger_kind == "schedule", Automation.next_run_at.is_not(None),
        Automation.next_run_at <= current).order_by(Automation.next_run_at, Automation.id)))
    queued: list[AutomationRun] = []
    for automation in due:
        counts["due"] += 1
        planned = aware(automation.next_run_at)
        run = queue_run(session, automation, f"schedule:{planned.isoformat()}")
        automation.next_run_at = compute_next_run(automation.trigger_config, current)
        if run is not None:
            queued.append(run)
    session.commit()
    for run in queued:
        send_task(RUN_TASK, args=[str(run.id)])
        counts["queued"] += 1
    return counts


def _latest_change(session: Session, automation: Automation, *, folder_ids: list[UUID] | None = None,
                   document_ids: list[UUID] | None = None) -> datetime | None:
    since = aware(automation.last_run_at or automation.created_at)
    indexed, modified = session.execute(select(func.max(Document.indexed_at), func.max(Document.modified_at)).where(
        Document.organization_id == automation.organization_id,
        Document.id.in_(document_ids) if document_ids is not None else Document.workspace_folder_id.in_(folder_ids or []),
        Document.index_status == "indexed", or_(Document.indexed_at > since, Document.modified_at > since))).one()
    stamps = [aware(item) for item in (indexed, modified) if item is not None and aware(item) > since]
    return max(stamps) if stamps else None


def enqueue_folder_changed(session: Session, *, workspace_folder_id: UUID, send_task: Callable[..., object]) -> dict[str, int]:
    """Post-sync hook: queue folder_changed automations whose scope contains the synced folder and changed."""
    counts = {"considered": 0, "queued": 0}
    candidates = list(session.scalars(select(Automation).where(
        Automation.enabled.is_(True), Automation.trigger_kind == "folder_changed")
        .order_by(Automation.created_at, Automation.id)))
    queued: list[AutomationRun] = []
    organization_id = session.scalar(select(WorkspaceFolder.organization_id).where(WorkspaceFolder.id == workspace_folder_id))
    for automation in candidates:
        node_ids = scope_node_ids(automation.scope)
        if node_ids:  # only changes inside the chosen folders (any depth) count
            if automation.organization_id != organization_id:
                continue
            documents = changed_document_ids(session, OrganizationScope(automation.organization_id),
                                             automation.created_by_user_id, node_ids, workspace_folder_id)
            if not documents:
                continue
            counts["considered"] += 1
            latest = _latest_change(session, automation, document_ids=documents)
        else:
            folder_ids = legacy_folder_ids(automation.scope)
            if workspace_folder_id not in folder_ids:
                continue
            counts["considered"] += 1
            latest = _latest_change(session, automation, folder_ids=folder_ids)
        if latest is None:
            continue
        run = queue_run(session, automation, f"folder:{latest.isoformat()}")
        if run is not None:
            queued.append(run)
    session.commit()
    for run in queued:
        send_task(RUN_TASK, args=[str(run.id)])
        counts["queued"] += 1
    return counts
