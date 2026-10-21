"""Space administration: lifecycle, membership and folder grants, all audited (ADR-0021).

Roles: organization owner/admin manage everything; a Space ``manager`` manages people of their own Space only.
Removal and revocation are logical. A Space the actor cannot see (other organization, not a member and not
an admin) is reported as not found, never as forbidden, so its existence does not leak.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit_usage.models import AuditLog
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.knowledge.models import Document
from app.organizations.models import Membership, MembershipRole
from app.spaces.models import SPACE_ROLE_MANAGER, SPACE_ROLES, Space, SpaceFolderGrant, SpaceMember
from app.workspaces.models import WorkspaceFolder

ADMIN_ROLES = (MembershipRole.OWNER, MembershipRole.ADMIN)


class SpaceDenied(PermissionError):
    pass


class SpaceConflict(ValueError):
    pass


class SpaceNotFound(LookupError):
    pass


@dataclass(frozen=True)
class SpaceView:
    id: UUID
    name: str
    description: str | None
    is_default: bool
    member_count: int
    folder_count: int
    my_role: str | None


@dataclass(frozen=True)
class SpaceMemberView:
    user_id: UUID
    email: str
    role: str


class SpaceService:
    def __init__(self, session: Session):
        self.session = session

    # -- lookups ---------------------------------------------------------------------------------
    @staticmethod
    def default_space_id(session: Session, organization_id: UUID) -> UUID | None:
        return session.scalar(select(Space.id).where(
            Space.organization_id == organization_id, Space.is_default.is_(True), Space.archived_at.is_(None)))

    def _actor_role(self, scope: OrganizationScope, actor_user_id: UUID) -> MembershipRole | None:
        return self.session.scalar(select(Membership.role).where(
            Membership.organization_id == scope.organization_id, Membership.user_id == actor_user_id,
            Membership.is_active.is_(True)))

    def _require_admin(self, scope: OrganizationScope, actor_user_id: UUID) -> None:
        if self._actor_role(scope, actor_user_id) not in ADMIN_ROLES:
            raise SpaceDenied("organization admin required")

    def _my_space_role(self, space_id: UUID, actor_user_id: UUID) -> str | None:
        return self.session.scalar(select(SpaceMember.role).where(
            SpaceMember.space_id == space_id, SpaceMember.user_id == actor_user_id, SpaceMember.removed_at.is_(None)))

    def _space(self, scope: OrganizationScope, actor_user_id: UUID, space_id: UUID) -> tuple[Space, bool, str | None]:
        """The Space, whether the actor is an org admin, and the actor's role inside it.

        Not found when archived/foreign, or when the actor is neither an org admin nor a member.
        """
        actor_role = self._actor_role(scope, actor_user_id)
        space = self.session.scalar(select(Space).where(
            Space.id == space_id, Space.organization_id == scope.organization_id, Space.archived_at.is_(None)))
        if actor_role is None or space is None:
            raise SpaceNotFound("space not found")
        is_admin = actor_role in ADMIN_ROLES
        my_role = self._my_space_role(space.id, actor_user_id)
        if not is_admin and my_role is None:
            raise SpaceNotFound("space not found")
        return space, is_admin, my_role

    def _manageable(self, scope: OrganizationScope, actor_user_id: UUID, space_id: UUID) -> Space:
        space, is_admin, my_role = self._space(scope, actor_user_id, space_id)
        if not (is_admin or my_role == SPACE_ROLE_MANAGER):
            raise SpaceDenied("space manager required")
        return space

    def _audit(self, scope: OrganizationScope, actor_user_id: UUID, action: str, target_type: str, target_id: UUID) -> None:
        self.session.add(AuditLog(
            organization_id=scope.organization_id, actor_user_id=actor_user_id,
            action=f"space.{action}", target_type=target_type, target_id=target_id))

    # -- lifecycle -------------------------------------------------------------------------------
    def create_space(
        self, scope: OrganizationScope, actor_user_id: UUID, name: str, description: str | None = None,
        is_default: bool = False,
    ) -> Space:
        self._require_admin(scope, actor_user_id)
        clean = self._clean_name(name)
        if is_default and self.default_space_id(self.session, scope.organization_id) is not None:
            raise SpaceConflict("a default space already exists")
        space = Space(
            organization_id=scope.organization_id, name=clean, name_key=clean.casefold(),
            description=description, is_default=is_default, created_by_user_id=actor_user_id)
        self._flush_unique(space)
        self._audit(scope, actor_user_id, "created", "space", space.id)
        return space

    def rename_space(
        self, scope: OrganizationScope, actor_user_id: UUID, space_id: UUID, name: str, description: str | None
    ) -> Space:
        space = self._manageable(scope, actor_user_id, space_id)
        clean = self._clean_name(name)
        space.name, space.name_key, space.description = clean, clean.casefold(), description
        self._flush_unique(space)
        self._audit(scope, actor_user_id, "renamed", "space", space.id)
        return space

    def archive_space(self, scope: OrganizationScope, actor_user_id: UUID, space_id: UUID) -> Space:
        self._require_admin(scope, actor_user_id)
        space, _, _ = self._space(scope, actor_user_id, space_id)
        if space.is_default:
            raise SpaceConflict("the default space cannot be archived")
        space.archived_at = datetime.now(UTC)
        self.session.flush()
        self._audit(scope, actor_user_id, "archived", "space", space.id)
        return space

    def set_default(self, scope: OrganizationScope, actor_user_id: UUID, space_id: UUID) -> Space:
        self._require_admin(scope, actor_user_id)
        space, _, _ = self._space(scope, actor_user_id, space_id)
        current = self.default_space_id(self.session, scope.organization_id)
        if current == space.id:
            return space
        if current is not None:
            self.session.get(Space, current).is_default = False
            self.session.flush()  # free the partial unique index before the new default is written
        space.is_default = True
        self.session.flush()
        self._audit(scope, actor_user_id, "default_changed", "space", space.id)
        return space

    # -- people ----------------------------------------------------------------------------------
    def add_member(
        self, scope: OrganizationScope, actor_user_id: UUID, space_id: UUID, user_id: UUID, role: str = "member"
    ) -> SpaceMember:
        space = self._manageable(scope, actor_user_id, space_id)
        self._check_role(role)
        active = self.session.scalar(select(Membership.id).where(
            Membership.organization_id == scope.organization_id, Membership.user_id == user_id,
            Membership.is_active.is_(True)))
        if active is None:
            raise SpaceDenied("only active organization members can join a space")
        existing = self.session.scalar(select(SpaceMember).where(
            SpaceMember.space_id == space.id, SpaceMember.user_id == user_id, SpaceMember.removed_at.is_(None)))
        if existing is not None:
            return existing
        member = SpaceMember(
            organization_id=scope.organization_id, space_id=space.id, user_id=user_id, role=role,
            added_by_user_id=actor_user_id)
        try:
            with self.session.begin_nested():
                self.session.add(member)
                self.session.flush()
        except IntegrityError:  # a concurrent request added the same person first: it is already there
            return self.session.scalar(select(SpaceMember).where(
                SpaceMember.space_id == space.id, SpaceMember.user_id == user_id, SpaceMember.removed_at.is_(None)))
        self._audit(scope, actor_user_id, "member_added", "space", space.id)
        self._audit(scope, actor_user_id, "member_added", "user", user_id)
        return member

    def remove_member(self, scope: OrganizationScope, actor_user_id: UUID, space_id: UUID, user_id: UUID) -> SpaceMember:
        space = self._manageable(scope, actor_user_id, space_id)
        member = self.session.scalar(select(SpaceMember).where(
            SpaceMember.space_id == space.id, SpaceMember.user_id == user_id, SpaceMember.removed_at.is_(None)))
        if member is None:
            raise SpaceNotFound("member not found")
        self._keep_one_manager(space.id, member)
        member.removed_at = datetime.now(UTC)
        member.removed_by_user_id = actor_user_id
        self.session.flush()
        self._audit(scope, actor_user_id, "member_removed", "space", space.id)
        self._audit(scope, actor_user_id, "member_removed", "user", user_id)
        self._apply_lost_access(scope.organization_id, [user_id])
        return member

    def set_member_role(
        self, scope: OrganizationScope, actor_user_id: UUID, space_id: UUID, user_id: UUID, role: str
    ) -> SpaceMember:
        space = self._manageable(scope, actor_user_id, space_id)
        self._check_role(role)
        member = self.session.scalar(select(SpaceMember).where(
            SpaceMember.space_id == space.id, SpaceMember.user_id == user_id, SpaceMember.removed_at.is_(None)))
        if member is None:
            raise SpaceNotFound("member not found")
        if role != SPACE_ROLE_MANAGER:
            self._keep_one_manager(space.id, member)
        member.role = role
        self.session.flush()
        self._audit(scope, actor_user_id, "member_role_changed", "space", space.id)
        return member

    def _apply_lost_access(self, organization_id: UUID, user_ids: Sequence[UUID], lost: set[UUID] | None = None) -> None:
        """Make the loss effective now: pause what the people can no longer run and unfollow stale queries."""
        from app.automations.space_access import pause_automations_for_lost_access
        from app.notifications.followed import clear_followed_state_for_lost_access

        for user_id in user_ids:
            pause_automations_for_lost_access(self.session, organization_id, user_id, lost)
            clear_followed_state_for_lost_access(self.session, organization_id, user_id)

    def _keep_one_manager(self, space_id: UUID, member: SpaceMember) -> None:
        """A Space always keeps a manager: the last one can be neither removed nor demoted."""
        if member.role != SPACE_ROLE_MANAGER:
            return
        others = self.session.scalar(select(func.count()).select_from(SpaceMember).where(
            SpaceMember.space_id == space_id, SpaceMember.role == SPACE_ROLE_MANAGER,
            SpaceMember.removed_at.is_(None), SpaceMember.id != member.id)) or 0
        if not others:
            raise SpaceConflict("a space needs at least one manager")

    def members(self, scope: OrganizationScope, actor_user_id: UUID, space_id: UUID) -> list[SpaceMemberView]:
        space, _, _ = self._space(scope, actor_user_id, space_id)
        rows = self.session.execute(
            select(SpaceMember.user_id, User.email, SpaceMember.role)
            .join(User, User.id == SpaceMember.user_id)
            .where(SpaceMember.space_id == space.id, SpaceMember.removed_at.is_(None))
            .order_by(User.email))
        return [SpaceMemberView(user_id, email, role) for user_id, email, role in rows]

    # -- folders ---------------------------------------------------------------------------------
    def grant_folder(
        self, scope: OrganizationScope, actor_user_id: UUID, space_id: UUID, workspace_folder_id: UUID,
        disclosure: dict[str, object],
    ) -> SpaceFolderGrant:
        self._require_admin(scope, actor_user_id)
        space, _, _ = self._space(scope, actor_user_id, space_id)
        if not disclosure or not disclosure.get("text_version"):
            raise ValueError("disclosure with text_version is required")
        folder_org = self.session.scalar(
            select(WorkspaceFolder.organization_id).where(WorkspaceFolder.id == workspace_folder_id))
        if folder_org != scope.organization_id:
            raise SpaceDenied("folder does not belong to this organization")
        existing = self.session.scalar(select(SpaceFolderGrant).where(
            SpaceFolderGrant.space_id == space.id, SpaceFolderGrant.workspace_folder_id == workspace_folder_id,
            SpaceFolderGrant.revoked_at.is_(None)))
        if existing is not None:
            return existing
        grant = SpaceFolderGrant(
            organization_id=scope.organization_id, space_id=space.id, workspace_folder_id=workspace_folder_id,
            granted_by_user_id=actor_user_id, disclosure=dict(disclosure))
        try:
            with self.session.begin_nested():
                self.session.add(grant)
                self.session.flush()
        except IntegrityError:  # granted concurrently: idempotent, report the existing grant
            return self.session.scalar(select(SpaceFolderGrant).where(
                SpaceFolderGrant.space_id == space.id, SpaceFolderGrant.workspace_folder_id == workspace_folder_id,
                SpaceFolderGrant.revoked_at.is_(None)))
        self._audit(scope, actor_user_id, "folder_granted", "space", space.id)
        self._audit(scope, actor_user_id, "folder_granted", "workspace_folder", workspace_folder_id)
        return grant

    def revoke_folder(
        self, scope: OrganizationScope, actor_user_id: UUID, space_id: UUID, workspace_folder_id: UUID
    ) -> SpaceFolderGrant:
        self._require_admin(scope, actor_user_id)
        space, _, _ = self._space(scope, actor_user_id, space_id)
        grant = self.session.scalar(select(SpaceFolderGrant).where(
            SpaceFolderGrant.space_id == space.id, SpaceFolderGrant.workspace_folder_id == workspace_folder_id,
            SpaceFolderGrant.revoked_at.is_(None)))
        if grant is None:
            raise SpaceNotFound("grant not found")
        grant.revoked_at = datetime.now(UTC)
        grant.revoked_by_user_id = actor_user_id
        self.session.flush()
        self._audit(scope, actor_user_id, "folder_revoked", "space", space.id)
        self._audit(scope, actor_user_id, "folder_revoked", "workspace_folder", workspace_folder_id)
        self._apply_lost_access(scope.organization_id, list(self.session.scalars(select(SpaceMember.user_id).where(
            SpaceMember.space_id == space.id, SpaceMember.removed_at.is_(None)))), {workspace_folder_id})
        return grant

    def apply_folder_changes(
        self, scope: OrganizationScope, actor_user_id: UUID, space_id: UUID,
        grant_ids: Sequence[UUID], revoke_ids: Sequence[UUID], disclosure: dict[str, object],
    ) -> tuple[list[UUID], list[UUID]]:
        """Apply a folder diff in one transaction (the caller commits or rolls back everything).

        Same rules as ``grant_folder``/``revoke_folder`` (org admin only, folders of this organization,
        audited); both directions are idempotent: a folder already granted / already not granted is skipped.
        Returns (granted, revoked) with the ids that actually changed."""
        self._require_admin(scope, actor_user_id)
        space, _, _ = self._space(scope, actor_user_id, space_id)
        to_grant = list(dict.fromkeys(grant_ids))
        to_revoke = [item for item in dict.fromkeys(revoke_ids) if item not in set(to_grant)]
        if to_grant:  # validate everything before the first write: a foreign folder fails the whole batch
            own = set(self.session.scalars(select(WorkspaceFolder.id).where(
                WorkspaceFolder.organization_id == scope.organization_id, WorkspaceFolder.id.in_(to_grant))))
            if own != set(to_grant):
                raise SpaceDenied("folder does not belong to this organization")
        granted: list[UUID] = []
        for folder_id in to_grant:
            before = self._folder_ids({space.id})
            self.grant_folder(scope, actor_user_id, space.id, folder_id, disclosure)
            if folder_id not in before:
                granted.append(folder_id)
        revoked: list[UUID] = []
        for folder_id in to_revoke:
            try:
                self.revoke_folder(scope, actor_user_id, space.id, folder_id)
                revoked.append(folder_id)
            except SpaceNotFound:  # already not granted: nothing to undo
                continue
        return granted, revoked

    def enter_space(self, scope: OrganizationScope, actor_user_id: UUID, space_id: UUID) -> SpaceMember:
        """An org admin joins a Space to read it: explicit, audited, visible to the Space's members (D2)."""
        self._require_admin(scope, actor_user_id)
        space, _, _ = self._space(scope, actor_user_id, space_id)
        member = self.session.scalar(select(SpaceMember).where(
            SpaceMember.space_id == space.id, SpaceMember.user_id == actor_user_id, SpaceMember.removed_at.is_(None)))
        if member is None:
            member = SpaceMember(
                organization_id=scope.organization_id, space_id=space.id, user_id=actor_user_id,
                role="member", added_by_user_id=actor_user_id)
            self.session.add(member)
            self.session.flush()
        self._audit(scope, actor_user_id, "admin_entered", "space", space.id)
        return member

    def member_impact(
        self, scope: OrganizationScope, actor_user_id: UUID, space_id: UUID, user_id: UUID
    ) -> dict[str, int]:
        """What removing ``user_id`` from the Space would cost them, considering their other Spaces. Read-only.

        Derived-content counters (conversations, automations, followed queries) are filled by T-H6."""
        space = self._manageable(scope, actor_user_id, space_id)
        if self._my_space_role(space.id, user_id) is None:
            raise SpaceNotFound("member not found")
        this_space = self._folder_ids({space.id})
        other_spaces = set(self.session.scalars(
            select(SpaceMember.space_id)
            .join(Space, Space.id == SpaceMember.space_id)
            .where(SpaceMember.organization_id == scope.organization_id, SpaceMember.user_id == user_id,
                   SpaceMember.removed_at.is_(None), Space.archived_at.is_(None), Space.id != space.id)))
        lost = this_space - self._folder_ids(other_spaces)
        documents_lost = 0
        if lost:
            files = (select(WorkspaceFolder.source_id, Document.external_file_id)
                     .join(Document, Document.workspace_folder_id == WorkspaceFolder.id)
                     .where(Document.organization_id == scope.organization_id,
                            Document.workspace_folder_id.in_(list(lost)), Document.index_status == "indexed")
                     .distinct().subquery())
            documents_lost = self.session.scalar(select(func.count()).select_from(files)) or 0
        from app.knowledge.derived import derived_impact

        return {"documents_lost": documents_lost,
                **derived_impact(self.session, scope.organization_id, user_id, lost_folder_ids=lost)}

    def _folder_ids(self, space_ids: set[UUID]) -> set[UUID]:
        if not space_ids:
            return set()
        return set(self.session.scalars(select(SpaceFolderGrant.workspace_folder_id).where(
            SpaceFolderGrant.space_id.in_(list(space_ids)), SpaceFolderGrant.revoked_at.is_(None))))

    # -- listing ---------------------------------------------------------------------------------
    def list_spaces_for_actor(self, scope: OrganizationScope, actor_user_id: UUID) -> list[SpaceView]:
        role = self._actor_role(scope, actor_user_id)
        if role is None:
            raise SpaceNotFound("space not found")
        query = select(Space).where(Space.organization_id == scope.organization_id, Space.archived_at.is_(None))
        mine = {
            space_id: member_role for space_id, member_role in self.session.execute(
                select(SpaceMember.space_id, SpaceMember.role).where(
                    SpaceMember.organization_id == scope.organization_id, SpaceMember.user_id == actor_user_id,
                    SpaceMember.removed_at.is_(None)))
        }
        if role not in ADMIN_ROLES:
            query = query.where(Space.id.in_(list(mine)))
        spaces = list(self.session.scalars(query.order_by(Space.name_key)))
        ids = [space.id for space in spaces]
        member_counts = self._counts(SpaceMember.space_id, SpaceMember.removed_at, ids)
        folder_counts = self._counts(SpaceFolderGrant.space_id, SpaceFolderGrant.revoked_at, ids)
        return [
            SpaceView(
                s.id, s.name, s.description, s.is_default, member_counts.get(s.id, 0),
                folder_counts.get(s.id, 0), mine.get(s.id))
            for s in spaces
        ]

    def _counts(self, space_column, closed_column, ids: Sequence[UUID]) -> dict[UUID, int]:
        if not ids:
            return {}
        rows = self.session.execute(
            select(space_column, func.count()).where(space_column.in_(list(ids)), closed_column.is_(None))
            .group_by(space_column))
        return {space_id: count for space_id, count in rows}

    # -- helpers ---------------------------------------------------------------------------------
    @staticmethod
    def _clean_name(name: str) -> str:
        clean = (name or "").strip()
        if not clean or len(clean) > 120:
            raise ValueError("space name must have 1-120 characters")
        return clean

    @staticmethod
    def _check_role(role: str) -> None:
        if role not in SPACE_ROLES:
            raise ValueError("invalid space role")

    def _flush_unique(self, space: Space) -> None:
        try:
            with self.session.begin_nested():
                self.session.add(space)
                self.session.flush()
        except IntegrityError as error:
            raise SpaceConflict("a space with this name already exists") from error
