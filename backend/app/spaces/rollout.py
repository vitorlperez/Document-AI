"""Coverage report for Spaces (ADR-0021): ``python -m app.spaces.rollout report [--organization ID]``.

Spaces always enforce (decision 2026-10-20), so the only operational question left is whether anyone or anything
sits outside every Space (invisible to everyone). Prints counts only, never names or content.

Exit codes: 0 ok (every organization covered), 2 some organization has a folder/person outside every Space,
1 usage or unknown organization.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.organizations.models import Membership, Organization
from app.spaces.models import Space, SpaceFolderGrant, SpaceMember
from app.workspaces.models import WorkspaceFolder


@dataclass(frozen=True)
class Coverage:
    organization_id: UUID
    folders_without_space: int
    people_without_space: int

    @property
    def clean(self) -> bool:
        return not (self.folders_without_space or self.people_without_space)


def _active_space_members(org_id: UUID):
    return select(SpaceMember.user_id).join(Space, Space.id == SpaceMember.space_id).where(
        SpaceMember.organization_id == org_id, SpaceMember.removed_at.is_(None), Space.archived_at.is_(None))


def coverage(session: Session, organization: Organization) -> Coverage:
    org_id = organization.id
    granted = exists().where(
        SpaceFolderGrant.workspace_folder_id == WorkspaceFolder.id, SpaceFolderGrant.revoked_at.is_(None),
        SpaceFolderGrant.space_id.in_(select(Space.id).where(Space.archived_at.is_(None))))
    folders = session.scalar(select(func.count()).select_from(WorkspaceFolder).where(
        WorkspaceFolder.organization_id == org_id, ~granted)) or 0
    members = _active_space_members(org_id).subquery()
    people = session.scalar(select(func.count()).select_from(Membership).where(
        Membership.organization_id == org_id, Membership.is_active.is_(True),
        Membership.user_id.not_in(select(members.c.user_id)))) or 0
    return Coverage(org_id, folders, people)


def run(argv: list[str], session: Session, out=sys.stdout) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.spaces.rollout")
    parser.add_argument("command", choices=("report",))
    parser.add_argument("--organization", type=UUID)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 1
    query = select(Organization).order_by(Organization.created_at)
    if args.organization is not None:
        query = query.where(Organization.id == args.organization)
    organizations = list(session.scalars(query))
    if args.organization is not None and not organizations:
        print("organização não encontrada", file=out)
        return 1
    clean = True
    for organization in organizations:
        state = coverage(session, organization)
        clean &= state.clean
        print(f"{state.organization_id} folders_without_space={state.folders_without_space} "
              f"people_without_space={state.people_without_space} clean={str(state.clean).lower()}", file=out)
    return 0 if clean else 2


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - wiring
    from app.core.config import get_settings
    from app.core.database import build_engine, build_session_factory

    with build_session_factory(build_engine(get_settings()))() as session:
        return run(list(sys.argv[1:] if argv is None else argv), session)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
