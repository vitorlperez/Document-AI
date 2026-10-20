"""Bell items as the person may see them now: content they lost access to is replaced by a notice (ADR-0021 §8.2)."""
from collections.abc import Collection
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.knowledge.derived_visibility import (
    HIDDEN_NOTICE,
    HIDDEN_REASON,
    Provenance,
    build_index,
    provenance_from_citations,
    provenance_from_data,
)
from app.notifications.models import Notification
from app.spaces.access import SpaceAccess, SpaceAccessResolver
from app.spaces.models import SpaceFolderGrant, SpaceMember

CONTENT_KINDS = frozenset({"followed_query_changed", "automation_result"})
# Plain references an item keeps even when its content is hidden (navigation only, no content).
_KEPT_KEYS = ("automation_id", "run_id", "saved_query_id", "workspace_folder_id", "template", "query_name")


def notification_provenance(item: Notification) -> Provenance:
    data = item.data if isinstance(item.data, dict) else {}
    return provenance_from_data(data.get("provenance")) or provenance_from_citations(data.get("citations"))


def lost_any_access(session: Session, access: SpaceAccess) -> bool:
    """Whether the person ever lost a Space membership or one of their Spaces lost a folder (conservative signal)."""
    org = access.organization_id
    removed = session.scalar(select(SpaceMember.id).where(
        SpaceMember.organization_id == org, SpaceMember.user_id == access.user_id,
        SpaceMember.removed_at.is_not(None)).limit(1))
    if removed is not None:
        return True
    return bool(access.spaces) and session.scalar(select(SpaceFolderGrant.id).where(
        SpaceFolderGrant.organization_id == org, SpaceFolderGrant.space_id.in_(list(access.spaces)),
        SpaceFolderGrant.revoked_at.is_not(None)).limit(1)) is not None


def notifications_visibility(session: Session, organization_id: UUID, user_id: UUID,
                             items: Collection[Notification]) -> dict[UUID, bool]:
    access = SpaceAccessResolver(session).resolve(scope=OrganizationScope(organization_id), user_id=user_id)
    provenance = {item.id: notification_provenance(item) for item in items}
    index = build_index(session, access, provenance.values())
    if not index.enforcing:
        return {item_id: True for item_id in provenance}
    lost = None
    result: dict[UUID, bool] = {}
    for item in items:
        if provenance[item.id]:
            result[item.id] = index.visible(provenance[item.id])
        elif item.kind in CONTENT_KINDS:
            lost = lost_any_access(session, access) if lost is None else lost
            result[item.id] = not lost  # nothing to check against: conservative once any access was lost
        else:
            result[item.id] = True
    return result


def hidden_data(data: object) -> dict[str, object]:
    kept = {key: data[key] for key in _KEPT_KEYS if isinstance(data, dict) and key in data}
    return {**kept, "hidden": True, "reason": HIDDEN_REASON}


def hidden_body() -> str:
    return HIDDEN_NOTICE
