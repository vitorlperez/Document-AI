"""Rollout CLI for Spaces (ADR-0021): ``python -m app.spaces.rollout <command>``.

Commands (all print counts only, never names or content):
  status                              mode of every organization
  report [--organization ID]          readiness and shadow divergence per organization
  off|shadow --organization ID        always allowed (this is the rollback)
  enforce --organization ID [--force] refuses an organization with a folder or a person outside every Space
  enforce --all-clean                 promotes only organizations in ``shadow`` with no pending item or divergence

Exit codes: 0 ok, 2 refused by a safety check, 1 usage or unknown organization.
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.organizations.models import Membership, Organization
from app.spaces.access import ADMIN_ROLES, MODE_ENFORCE, MODE_OFF, MODE_SHADOW, SpaceAccessResolver
from app.spaces.models import Space, SpaceFolderGrant, SpaceMember
from app.workspaces.models import WorkspaceFolder

logger = logging.getLogger("document_intelligence.spaces.rollout")
MODES = (MODE_OFF, MODE_SHADOW, MODE_ENFORCE)
REFUSAL = "organização tem pasta/pessoa sem Espaço"


@dataclass(frozen=True)
class Readiness:
    organization_id: UUID
    mode: str
    folders_without_space: int
    people_without_space: int
    divergent_people: int

    @property
    def clean(self) -> bool:
        return not (self.folders_without_space or self.people_without_space or self.divergent_people)


def _active_space_members(org_id: UUID):
    return select(SpaceMember.user_id).join(Space, Space.id == SpaceMember.space_id).where(
        SpaceMember.organization_id == org_id, SpaceMember.removed_at.is_(None), Space.archived_at.is_(None))


def readiness(session: Session, organization: Organization, *, with_divergence: bool = True) -> Readiness:
    org_id = organization.id
    granted = exists().where(
        SpaceFolderGrant.workspace_folder_id == WorkspaceFolder.id, SpaceFolderGrant.revoked_at.is_(None),
        SpaceFolderGrant.space_id.in_(select(Space.id).where(Space.archived_at.is_(None))))
    folders = session.scalar(select(func.count()).select_from(WorkspaceFolder).where(
        WorkspaceFolder.organization_id == org_id, ~granted)) or 0
    members = _active_space_members(org_id).subquery()
    people = session.scalars(select(Membership.user_id).where(
        Membership.organization_id == org_id, Membership.is_active.is_(True),
        Membership.user_id.not_in(select(members.c.user_id)))).all()
    divergent = 0
    if with_divergence:
        resolver, scope = SpaceAccessResolver(session), OrganizationScope(org_id)
        for user_id, role in session.execute(select(Membership.user_id, Membership.role).where(
                Membership.organization_id == org_id, Membership.is_active.is_(True))).all():
            admin = role in ADMIN_ROLES
            legacy = resolver._legacy(scope, user_id, None, admin)
            spaces = resolver._granted(scope, user_id, None, False, admin)
            divergent += legacy.folder_ids != spaces.folder_ids
    return Readiness(org_id, organization.spaces_resolver_mode, folders, len(people), divergent)


def set_mode(session: Session, organization: Organization, mode: str, *, force: bool = False) -> bool:
    """Apply ``mode``. ``enforce`` is refused (False) with pending folders/people unless ``force``."""
    if mode not in MODES:
        raise ValueError(f"unknown mode: {mode}")
    if mode == MODE_ENFORCE and not force:
        state = readiness(session, organization, with_divergence=False)
        if state.folders_without_space or state.people_without_space:
            return False
    previous, organization.spaces_resolver_mode = organization.spaces_resolver_mode, mode
    session.flush()
    logger.warning("spaces.rollout_mode_changed", extra={
        "organization_id": str(organization.id), "from": previous, "to": mode, "forced": force})
    return True


def _organizations(session: Session, organization_id: UUID | None) -> list[Organization]:
    query = select(Organization).order_by(Organization.created_at)
    if organization_id is not None:
        query = query.where(Organization.id == organization_id)
    return list(session.scalars(query))


def run(argv: list[str], session: Session, out=sys.stdout) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.spaces.rollout")
    parser.add_argument("command", choices=("status", "report", *MODES))
    parser.add_argument("--organization", type=UUID)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--all-clean", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 1
    organizations = _organizations(session, args.organization)
    if args.organization is not None and not organizations:
        print("organização não encontrada", file=out)
        return 1
    if args.command == "status":
        for organization in organizations:
            print(f"{organization.id} {organization.spaces_resolver_mode}", file=out)
        return 0
    if args.command == "report":
        for organization in organizations:
            state = readiness(session, organization)
            print(f"{state.organization_id} mode={state.mode} folders_without_space={state.folders_without_space} "
                  f"people_without_space={state.people_without_space} divergent_people={state.divergent_people} "
                  f"clean={str(state.clean).lower()}", file=out)
        return 0
    if args.command == MODE_ENFORCE and args.all_clean:
        promoted = 0
        for organization in organizations:
            if organization.spaces_resolver_mode == MODE_SHADOW and readiness(session, organization).clean:
                promoted += set_mode(session, organization, MODE_ENFORCE)
        session.commit()
        print(f"promovidas={promoted}", file=out)
        return 0
    if args.organization is None:
        print("informe --organization (ou enforce --all-clean)", file=out)
        return 1
    organization = organizations[0]
    if not set_mode(session, organization, args.command, force=args.force):
        session.rollback()
        print(f"recusado: {REFUSAL} (use --force para ignorar)", file=out)
        return 2
    session.commit()
    print(f"{organization.id} {organization.spaces_resolver_mode}", file=out)
    return 0


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - wiring
    from app.core.config import get_settings
    from app.core.database import build_engine, build_session_factory

    with build_session_factory(build_engine(get_settings()))() as session:
        return run(list(sys.argv[1:] if argv is None else argv), session)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
