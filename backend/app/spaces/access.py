"""The single answer to "which synchronized scopes may this person read?" (ADR-0021 D3).

Fail-closed: database errors propagate, an empty result means zero content, and the only "everything"
answer is the explicit rollout mode ``off``/``shadow`` (legacy behaviour for organizations not yet enforcing).
"""

import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.access_errors import SyncAccessDenied
from app.core.scoping import OrganizationScope
from app.organizations.models import Membership, Organization
from app.spaces.models import Space, SpaceFolderGrant, SpaceMember
from app.spaces.service import SpaceNotFound
from app.workspaces.models import WorkspaceFolder

logger = logging.getLogger(__name__)
MODE_OFF, MODE_SHADOW, MODE_ENFORCE = "off", "shadow", "enforce"


@dataclass(frozen=True)
class SpaceRef:
    id: UUID
    name: str


@dataclass(frozen=True)
class SpaceAccess:
    """What ONE person can read in one organization at one instant. Immutable; computed per request."""

    organization_id: UUID
    user_id: UUID
    spaces: Mapping[UUID, SpaceRef]
    folder_spaces: Mapping[UUID, frozenset[UUID]]

    @property
    def folder_ids(self) -> frozenset[UUID]:
        return frozenset(self.folder_spaces)

    def allows(self, folder_id: UUID) -> bool:
        return folder_id in self.folder_spaces

    def spaces_of(self, folder_id: UUID) -> tuple[SpaceRef, ...]:
        """Badges: only Spaces of this person that grant the folder."""
        refs = (self.spaces[space_id] for space_id in self.folder_spaces.get(folder_id, ()) if space_id in self.spaces)
        return tuple(sorted(refs, key=lambda ref: (ref.name.casefold(), str(ref.id))))


class SpaceAccessResolver:
    def __init__(self, session: Session):
        self.session = session

    def resolve(
        self, *, scope: OrganizationScope, user_id: UUID, space_ids: Collection[UUID] | None = None,
        strict: bool = False,
    ) -> SpaceAccess:
        """``space_ids`` only narrows. ``strict`` (routes) turns a Space the person is not in into SpaceNotFound."""
        mode = self._require_active_member(scope, user_id)
        if mode == MODE_OFF:
            return self._legacy(scope, user_id)
        granted = self._granted(scope, user_id, space_ids, strict)
        if mode == MODE_SHADOW:
            legacy = self._legacy(scope, user_id)
            only_legacy, only_spaces = legacy.folder_ids - granted.folder_ids, granted.folder_ids - legacy.folder_ids
            if only_legacy or only_spaces:
                logger.warning("spaces.shadow_divergence", extra={
                    "organization_id": str(scope.organization_id), "user_id": str(user_id),
                    "only_legacy": len(only_legacy), "only_spaces": len(only_spaces)})
            return legacy
        return granted  # enforce, and any unknown mode value fails closed to the Space rules

    def require_folders(
        self, *, scope: OrganizationScope, user_id: UUID, workspace_folder_ids: Collection[UUID],
        access: SpaceAccess | None = None,
    ) -> list[WorkspaceFolder]:
        """One access resolution + one folder query for any number of folders (replaces the per-folder loop).

        Pass the ``access`` already resolved for this request to avoid resolving twice."""
        access = access or self.resolve(scope=scope, user_id=user_id)
        wanted = list(dict.fromkeys(workspace_folder_ids))
        if any(folder_id not in access.folder_ids for folder_id in wanted):
            raise SyncAccessDenied("workspace access denied")
        if not wanted:
            return []
        rows = list(self.session.execute(select(WorkspaceFolder).where(
            WorkspaceFolder.id.in_(wanted), WorkspaceFolder.organization_id == scope.organization_id)).scalars())
        if len(rows) != len(wanted):
            raise SyncAccessDenied("workspace access denied")
        return rows

    def require_folder(self, *, scope: OrganizationScope, user_id: UUID, workspace_folder_id: UUID) -> WorkspaceFolder:
        return self.require_folders(scope=scope, user_id=user_id, workspace_folder_ids=[workspace_folder_id])[0]

    # -- internals -------------------------------------------------------------------------------
    def _require_active_member(self, scope: OrganizationScope, user_id: UUID) -> str:
        """Membership check and rollout mode in one statement; returns the mode."""
        row = self.session.execute(
            select(Organization.spaces_resolver_mode)
            .join(Membership, Membership.organization_id == Organization.id)
            .where(Organization.id == scope.organization_id, Membership.user_id == user_id,
                   Membership.is_active.is_(True))
            .limit(1)).first()
        if row is None:
            raise SyncAccessDenied("company library access denied")
        return row[0] or MODE_OFF

    def _legacy(self, scope: OrganizationScope, user_id: UUID) -> SpaceAccess:
        ids = self.session.execute(
            select(WorkspaceFolder.id).where(WorkspaceFolder.organization_id == scope.organization_id)).scalars()
        return SpaceAccess(scope.organization_id, user_id, {}, {folder_id: frozenset() for folder_id in ids})

    def _granted(
        self, scope: OrganizationScope, user_id: UUID, space_ids: Collection[UUID] | None, strict: bool
    ) -> SpaceAccess:
        org = scope.organization_id
        spaces_query = (
            select(Space.id, Space.name)
            .join(SpaceMember, SpaceMember.space_id == Space.id)
            .where(Space.organization_id == org, Space.archived_at.is_(None), SpaceMember.organization_id == org,
                   SpaceMember.user_id == user_id, SpaceMember.removed_at.is_(None)))
        wanted = set(space_ids) if space_ids is not None else None
        if wanted is not None:
            spaces_query = spaces_query.where(Space.id.in_(list(wanted)))
        spaces = {space_id: SpaceRef(space_id, name) for space_id, name in self.session.execute(spaces_query)}
        if strict and wanted is not None and wanted - set(spaces):
            raise SpaceNotFound("space not found")
        folder_spaces: dict[UUID, set[UUID]] = {}
        if spaces:
            rows = self.session.execute(
                select(SpaceFolderGrant.workspace_folder_id, SpaceFolderGrant.space_id)
                .join(WorkspaceFolder, WorkspaceFolder.id == SpaceFolderGrant.workspace_folder_id)
                .where(SpaceFolderGrant.organization_id == org, SpaceFolderGrant.revoked_at.is_(None),
                       SpaceFolderGrant.space_id.in_(list(spaces)), WorkspaceFolder.organization_id == org))
            for folder_id, space_id in rows:
                folder_spaces.setdefault(folder_id, set()).add(space_id)
        return SpaceAccess(org, user_id, spaces, {k: frozenset(v) for k, v in folder_spaces.items()})
