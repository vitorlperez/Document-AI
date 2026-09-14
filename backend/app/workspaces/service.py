import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.integrations.google_drive import GoogleAccessDenied
from app.integrations.models import DataSource
from app.organizations.models import Membership, MembershipRole
from app.workspaces.models import WorkspaceFolder, WorkspaceFolderSelection

SCOPE_SELECTED = "selected"
SCOPE_ALL_ACCESSIBLE = "all_accessible"
SELECTION_FOLDER = "folder"
SELECTION_ROOT_FILES = "root_files"
SELECTION_ALL_ACCESSIBLE = "all_accessible"


@dataclass(frozen=True)
class WorkspaceScope:
    mode: str
    folder_ids: tuple[str, ...] = ()
    include_root_files: bool = False


class WorkspaceService:
    def __init__(self, session: Session):
        self.session = session

    def require_member_access(self, *, scope: OrganizationScope, user_id: UUID, workspace_folder_id: UUID) -> WorkspaceFolder:
        member = self.session.scalar(select(Membership).where(Membership.organization_id == scope.organization_id, Membership.user_id == user_id, Membership.is_active.is_(True)))
        folder = self.session.scalar(select(WorkspaceFolder).where(WorkspaceFolder.id == workspace_folder_id, WorkspaceFolder.organization_id == scope.organization_id))
        if member is None or folder is None:
            raise GoogleAccessDenied("workspace access denied")
        return folder

    def folders(self, *, scope: OrganizationScope, user_id: UUID) -> list[WorkspaceFolder]:
        member = self.session.scalar(select(Membership).where(Membership.organization_id == scope.organization_id, Membership.user_id == user_id, Membership.is_active.is_(True)))
        if member is None:
            raise GoogleAccessDenied("workspace access denied")
        return list(self.session.scalars(select(WorkspaceFolder).where(WorkspaceFolder.organization_id == scope.organization_id).order_by(WorkspaceFolder.name)))

    def selections(self, *, scope: OrganizationScope, workspace_folder_id: UUID) -> list[WorkspaceFolderSelection]:
        return list(self.session.scalars(select(WorkspaceFolderSelection).join(WorkspaceFolder, WorkspaceFolder.id == WorkspaceFolderSelection.workspace_folder_id).where(WorkspaceFolderSelection.workspace_folder_id == workspace_folder_id, WorkspaceFolder.organization_id == scope.organization_id).order_by(WorkspaceFolderSelection.kind, WorkspaceFolderSelection.external_folder_id)))

    def support_metadata(self, *, scope: OrganizationScope) -> list[WorkspaceFolder]:
        """Return only operational folder metadata after platform grant authorization."""
        return list(self.session.scalars(select(WorkspaceFolder).where(WorkspaceFolder.organization_id == scope.organization_id).order_by(WorkspaceFolder.name, WorkspaceFolder.id)))

    def select_scope(self, *, scope: OrganizationScope, user_id: UUID, source_id: UUID, requested: WorkspaceScope, uniform_access_confirmed: bool, available_folder_names: dict[str, str], name: str | None = None) -> WorkspaceFolder:
        self._require_connected_source(scope=scope, user_id=user_id, source_id=source_id)
        if not uniform_access_confirmed:
            raise ValueError("uniform access confirmation is required")
        normalized = self._normalize_scope(requested=requested, available_folder_names=available_folder_names)
        scope_key = self._scope_key(normalized)
        existing = self.session.scalar(select(WorkspaceFolder).where(WorkspaceFolder.source_id == source_id, WorkspaceFolder.external_folder_id == scope_key))
        if existing is not None:
            return existing
        # Before F-014, the legacy external folder ID was stored directly on
        # the workspace. The additive migration creates its selection row but
        # deliberately retains that value, so recognize it on re-selection.
        # This keeps an existing index and its usage history canonical.
        legacy = self._legacy_match(source_id=source_id, requested=normalized)
        if legacy is not None:
            return legacy
        folder = WorkspaceFolder(organization_id=scope.organization_id, source_id=source_id, external_folder_id=scope_key, name=name or self._default_name(normalized, available_folder_names), uniform_access_confirmed=True)
        try:
            with self.session.begin_nested():
                self.session.add(folder)
                self.session.flush()
                for kind, external_folder_id in self._selection_rows(normalized):
                    self.session.add(WorkspaceFolderSelection(workspace_folder_id=folder.id, kind=kind, external_folder_id=external_folder_id))
                self.session.flush()
        except IntegrityError:
            folder = self.session.scalar(select(WorkspaceFolder).where(WorkspaceFolder.source_id == source_id, WorkspaceFolder.external_folder_id == scope_key))
            if folder is not None:
                return folder
            raise
        return folder

    def select_folder(self, *, scope: OrganizationScope, user_id: UUID, source_id: UUID, external_folder_id: str, name: str, uniform_access_confirmed: bool, available_folder_ids: set[str]) -> WorkspaceFolder:
        """Compatibility facade for the original single-folder endpoint."""
        return self.select_scope(scope=scope, user_id=user_id, source_id=source_id, requested=WorkspaceScope(mode=SCOPE_SELECTED, folder_ids=(external_folder_id,)), uniform_access_confirmed=uniform_access_confirmed, available_folder_names={folder_id: folder_id for folder_id in available_folder_ids}, name=name)

    def _require_connected_source(self, *, scope: OrganizationScope, user_id: UUID, source_id: UUID) -> DataSource:
        member = self.session.scalar(select(Membership).where(Membership.organization_id == scope.organization_id, Membership.user_id == user_id, Membership.is_active.is_(True), Membership.role.in_([MembershipRole.OWNER, MembershipRole.ADMIN])))
        source = self.session.scalar(select(DataSource).where(DataSource.id == source_id, DataSource.organization_id == scope.organization_id, DataSource.status == "connected"))
        if member is None or source is None:
            raise GoogleAccessDenied("workspace access denied")
        return source

    def _legacy_match(self, *, source_id: UUID, requested: WorkspaceScope) -> WorkspaceFolder | None:
        requested_rows = self._selection_rows(requested)
        candidates = self.session.scalars(
            select(WorkspaceFolder).where(
                WorkspaceFolder.source_id == source_id,
                ~WorkspaceFolder.external_folder_id.startswith("scope:"),
            )
        )
        for candidate in candidates:
            existing_rows = [
                (item.kind, item.external_folder_id)
                for item in self.session.scalars(
                    select(WorkspaceFolderSelection)
                    .where(WorkspaceFolderSelection.workspace_folder_id == candidate.id)
                    .order_by(WorkspaceFolderSelection.kind, WorkspaceFolderSelection.external_folder_id)
                )
            ]
            if existing_rows == sorted(requested_rows):
                return candidate
        return None

    @staticmethod
    def _normalize_scope(*, requested: WorkspaceScope, available_folder_names: dict[str, str]) -> WorkspaceScope:
        if requested.mode == SCOPE_ALL_ACCESSIBLE:
            if requested.folder_ids or requested.include_root_files:
                raise ValueError("all accessible mode cannot include folder or root selections")
            return WorkspaceScope(mode=SCOPE_ALL_ACCESSIBLE)
        if requested.mode != SCOPE_SELECTED:
            raise ValueError("scope mode is invalid")
        folder_ids = tuple(sorted(set(requested.folder_ids)))
        if any(folder_id not in available_folder_names for folder_id in folder_ids):
            raise ValueError("folder is not available from this source")
        if not folder_ids and not requested.include_root_files:
            raise ValueError("select at least one folder or root files")
        return WorkspaceScope(mode=SCOPE_SELECTED, folder_ids=folder_ids, include_root_files=requested.include_root_files)

    @staticmethod
    def _scope_key(scope: WorkspaceScope) -> str:
        serialized = json.dumps({"mode": scope.mode, "folder_ids": scope.folder_ids, "include_root_files": scope.include_root_files}, separators=(",", ":"), sort_keys=True)
        return f"scope:{hashlib.sha256(serialized.encode()).hexdigest()}"

    @staticmethod
    def _selection_rows(scope: WorkspaceScope) -> list[tuple[str, str]]:
        if scope.mode == SCOPE_ALL_ACCESSIBLE:
            return [(SELECTION_ALL_ACCESSIBLE, "")]
        rows = [(SELECTION_FOLDER, folder_id) for folder_id in scope.folder_ids]
        if scope.include_root_files:
            rows.append((SELECTION_ROOT_FILES, ""))
        return rows

    @staticmethod
    def _default_name(scope: WorkspaceScope, available_folder_names: dict[str, str]) -> str:
        if scope.mode == SCOPE_ALL_ACCESSIBLE:
            return "Todo o Drive acessível"
        names = [available_folder_names[folder_id] for folder_id in scope.folder_ids]
        parts = names[:2]
        if len(names) > 2:
            parts.append(f"+{len(names) - 2} pastas")
        if scope.include_root_files:
            parts.append("arquivos da raiz")
        return " · ".join(parts)
