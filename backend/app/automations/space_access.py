"""Automations after a person loses access to part of their scope (ADR-0021 §8.2).

E-mail and webhook deliveries are irrevocable, so the mitigation is to stop producing more: the creator's
automations that no longer run with the creator's access are paused (``enabled = False``, no new run status) and
the creator is told why; a person who lost access is dropped from other people's recipient lists.
"""
from collections.abc import Collection
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.automations.executor import accessible_folders
from app.automations.models import Automation, AutomationRun
from app.automations.scope import legacy_folder_ids, node_access, scope_node_ids
from app.core.scoping import OrganizationScope
from app.knowledge.derived_visibility import (
    HIDDEN_REASON,
    Provenance,
    build_index,
    provenance_from_citations,
    provenance_from_data,
)
from app.notifications.service import NotificationService
from app.spaces.access import SpaceAccessResolver

PAUSED_KIND = "automation_paused"


def _still_runnable(session: Session, scope: OrganizationScope, automation: Automation, user_id: UUID,
                    allowed: set[UUID] | None) -> bool:
    nodes = scope_node_ids(automation.scope)
    if nodes:
        return node_access(session, scope, user_id, nodes) == "ok"
    folders = set(legacy_folder_ids(automation.scope))
    return bool(folders) and allowed is not None and folders <= allowed


def pause_automations_for_lost_access(
    session: Session, organization_id: UUID, user_id: UUID, lost_folder_ids: Collection[UUID] | None = None,
) -> list[UUID]:
    """Pause what ``user_id`` created and can no longer run; clean them out of recipient lists. Idempotent.

    ``lost_folder_ids`` is a hint to skip legacy automations whose folders did not change; node-scoped ones are
    always rechecked against today's access. Returns the paused automation ids."""
    scope = OrganizationScope(organization_id)
    allowed = accessible_folders(session, scope, user_id)
    lost = set(lost_folder_ids) if lost_folder_ids is not None else None
    paused: list[UUID] = []
    own = session.scalars(select(Automation).where(
        Automation.organization_id == organization_id, Automation.created_by_user_id == user_id,
        Automation.enabled.is_(True)).order_by(Automation.created_at, Automation.id))
    for automation in own:
        legacy = set(legacy_folder_ids(automation.scope))
        if lost is not None and not scope_node_ids(automation.scope) and legacy and not (legacy & lost):
            continue
        if _still_runnable(session, scope, automation, user_id, allowed):
            continue
        automation.enabled = False
        automation.next_run_at = None
        NotificationService(session).notify(
            scope=scope, user_id=user_id, kind=PAUSED_KIND, title=f"“{automation.name}” foi pausada",
            body="Você perdeu o acesso a parte das pastas desta automação, então ela foi pausada. "
                 "Revise o escopo para reativá-la.",
            data={"automation_id": str(automation.id), "reason": "creator_access_lost"})
        paused.append(automation.id)
    key = str(user_id)
    for automation in session.scalars(select(Automation).where(
            Automation.organization_id == organization_id, Automation.created_by_user_id != user_id)):
        if key not in {str(item) for item in automation.recipients or []}:
            continue
        nodes = scope_node_ids(automation.scope)
        if nodes:
            ok = node_access(session, scope, user_id, nodes) == "ok"
        else:
            folders = set(legacy_folder_ids(automation.scope))
            ok = bool(folders) and allowed is not None and folders <= allowed
        if not ok:
            automation.recipients = [item for item in automation.recipients if str(item) != key]
    session.flush()
    return paused


def run_provenance(run: AutomationRun) -> Provenance:
    """What a stored run was made of: its recorded provenance, else the documents its citations name."""
    result = run.result if isinstance(run.result, dict) else {}
    recorded = provenance_from_data(result.get("provenance"))
    return recorded or provenance_from_citations(result.get("citations"))


def runs_visibility(session: Session, organization_id: UUID, user_id: UUID,
                    runs: Collection[AutomationRun]) -> dict[UUID, bool]:
    """``run.id -> viewer may still read its result``, in a constant number of queries."""
    access = SpaceAccessResolver(session).resolve(scope=OrganizationScope(organization_id), user_id=user_id)
    provenance = {run.id: run_provenance(run) for run in runs}
    index = build_index(session, access, provenance.values())
    return {run_id: index.visible(item) for run_id, item in provenance.items()}


def hidden_result() -> dict[str, object]:
    return {"hidden": True, "reason": HIDDEN_REASON}
