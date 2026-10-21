"""Default Space enrolment hooks used by organization and workspace flows (ADR-0021 D9).

Every organization has a default Space ("Geral"): created with the organization and guaranteed for older ones
by migration 0038. Without it (should not happen) a hook is a no-op and the person/folder stays outside every Space.
"""

from collections.abc import Collection
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.spaces.models import SPACE_ROLE_MEMBER, Space, SpaceFolderGrant, SpaceMember

DISCLOSURE_TEXT_VERSION = "v1"


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
        if not targets:  # every requested Space is gone/invalid: never leave the person in zero Spaces
            default = default_space_id(session, organization_id)
            targets = [default] if default is not None else []
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
    else:  # an explicit (possibly empty) list is the caller's decision, e.g. the Drive robot grants its own
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
