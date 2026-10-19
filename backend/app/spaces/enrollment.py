"""Default Space enrolment hooks used by organization and workspace flows (ADR-0021 D9).

Organizations that predate the backfill have no default Space: every hook is then a no-op, so legacy
behaviour is untouched until the migration/rollout has run.
"""

import os
from collections.abc import Collection
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.spaces.models import SPACE_ROLE_MEMBER, Space, SpaceFolderGrant, SpaceMember

MODES = ("off", "shadow", "enforce")
DISCLOSURE_TEXT_VERSION = "v1"


def new_org_mode() -> str:
    """Resolver mode for organizations created after the deploy (SPACES_NEW_ORG_MODE, default shadow)."""
    mode = os.environ.get("SPACES_NEW_ORG_MODE", "shadow").strip().lower()
    return mode if mode in MODES else "shadow"


def default_space_id(session: Session, organization_id: UUID) -> UUID | None:
    return session.scalar(select(Space.id).where(
        Space.organization_id == organization_id, Space.is_default.is_(True), Space.archived_at.is_(None)))


def valid_space_ids(session: Session, organization_id: UUID, space_ids: Collection[UUID]) -> list[UUID]:
    if not space_ids:
        return []
    return list(session.scalars(select(Space.id).where(
        Space.organization_id == organization_id, Space.archived_at.is_(None), Space.id.in_(list(space_ids)))))


def enroll_member(
    session: Session, organization_id: UUID, user_id: UUID, space_ids: Collection[UUID] | None = None,
    added_by_user_id: UUID | None = None, role: str = SPACE_ROLE_MEMBER,
) -> list[UUID]:
    """Add a person to ``space_ids`` (unknown ones ignored) or, when None, to the default Space."""
    if space_ids is None:
        default = default_space_id(session, organization_id)
        targets = [default] if default is not None else []
    else:
        targets = valid_space_ids(session, organization_id, space_ids)
    joined = []
    for space_id in targets:
        exists = session.scalar(select(SpaceMember.id).where(
            SpaceMember.space_id == space_id, SpaceMember.user_id == user_id, SpaceMember.removed_at.is_(None)))
        if exists is None:
            session.add(SpaceMember(
                organization_id=organization_id, space_id=space_id, user_id=user_id, role=role,
                added_by_user_id=added_by_user_id))
            joined.append(space_id)
    session.flush()
    return joined


def deactivate_member(session: Session, organization_id: UUID, user_id: UUID, removed_by_user_id: UUID | None) -> None:
    now = datetime.now(UTC)
    for member in session.scalars(select(SpaceMember).where(
            SpaceMember.organization_id == organization_id, SpaceMember.user_id == user_id,
            SpaceMember.removed_at.is_(None))):
        member.removed_at, member.removed_by_user_id = now, removed_by_user_id
    session.flush()


def grant_scope(
    session: Session, organization_id: UUID, workspace_folder_id: UUID, granted_by_user_id: UUID | None,
    space_ids: Collection[UUID] | None = None,
) -> list[UUID]:
    """Grant a synchronized scope to ``space_ids`` or (None) the default Space. Idempotent."""
    if space_ids is None:
        default = default_space_id(session, organization_id)
        targets = [default] if default is not None else []
    else:
        targets = list(dict.fromkeys(space_ids))
    granted = []
    for space_id in targets:
        exists = session.scalar(select(SpaceFolderGrant.id).where(
            SpaceFolderGrant.space_id == space_id, SpaceFolderGrant.workspace_folder_id == workspace_folder_id,
            SpaceFolderGrant.revoked_at.is_(None)))
        if exists is not None:
            continue
        member_count = session.scalar(select(func.count()).select_from(SpaceMember).where(
            SpaceMember.space_id == space_id, SpaceMember.removed_at.is_(None))) or 0
        session.add(SpaceFolderGrant(
            organization_id=organization_id, space_id=space_id, workspace_folder_id=workspace_folder_id,
            granted_by_user_id=granted_by_user_id,
            disclosure={
                "text_version": DISCLOSURE_TEXT_VERSION, "member_count": member_count,
                "acknowledged_at": datetime.now(UTC).isoformat()}))
        granted.append(space_id)
    session.flush()
    return granted
