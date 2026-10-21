"""Tenant-scoped robot assignment, verified grants and revocation retention."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update

from app.audit_usage.models import AuditLog
from app.core.scoping import OrganizationScope
from app.integrations.google_drive import RemoteFolder
from app.integrations.google_drive_sa import (
    FolderAccessLost,
    NestedInLinked,
    RobotUnavailable,
    SaDriveClient,
    SaRequestError,
    ServiceAccountKeyCipher,
    ServiceAccountTokenSource,
    parse_folder_id,
)
from app.integrations.google_sa_models import DriveFolderLink, GoogleSaIdentity
from app.integrations.google_sa_provisioner import PROVISIONING, PROVISIONING_FAILED
from app.integrations.models import DataSource
from app.integrations.oauth_base import OAuthConnectionServiceBase
from app.knowledge.models import Document, DocumentChunk
from app.library.models import LibraryNode
from app.organizations.models import Organization
from app.spaces import enrollment
from app.spaces.service import SpaceNotFound, SpaceService
from app.workspaces.models import WorkspaceFolder, WorkspaceFolderSelection
from app.workspaces.service import WorkspaceScope, WorkspaceService

logger = logging.getLogger("document_intelligence.integration")


def utc(value):
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


def key_cipher(settings):
    previous = settings.google_sa_key_encryption_previous_keys
    return ServiceAccountKeyCipher(
        settings.cipher_keys("google_drive_sa")[0],
        fallback_keys=previous.get_secret_value().split(",") if previous else (),
    )


class DriveSaConnectionService(OAuthConnectionServiceBase):
    provider = "google_drive_sa"

    def __init__(self, session, settings, *, client=None, credential_factory=None):
        super().__init__(session, key_cipher(settings))
        self.settings = settings
        self.client = client or SaDriveClient()
        self.credential_factory = credential_factory
        self._tokens = {}

    def gate(self, organization_id):
        if not self.settings.google_sa_enabled_for(organization_id):
            raise SaRequestError("disabled", 404)

    def require_admin(self, *, scope, user_id):
        self.gate(scope.organization_id)
        try:
            super().require_admin(scope=scope, user_id=user_id)
        except PermissionError:
            raise SaRequestError("forbidden", 403) from None

    def source(self, *, scope, user_id, source_id):
        self.require_admin(scope=scope, user_id=user_id)
        source = self._own_source(organization_id=scope.organization_id, source_id=source_id)
        if not source or source.status == "disconnected":
            raise SaRequestError("not_shared", 404)
        return source

    def identity(self, source):
        self.gate(source.organization_id)
        if source.status in (PROVISIONING, PROVISIONING_FAILED):
            raise SaRequestError("provisioning", 409)
        identity = self.session.scalar(
            select(GoogleSaIdentity).where(
                GoogleSaIdentity.id == source.sa_identity_id,
                GoogleSaIdentity.organization_id == source.organization_id,
                GoogleSaIdentity.status == "assigned",
            )
        )
        if identity is None or not identity.encrypted_key:
            raise RobotUnavailable("robot_unavailable")
        return identity

    def credentials(self, source):
        identity = self.identity(source)
        if self.credential_factory:
            return self.credential_factory(identity)
        token = self._tokens.setdefault(
            identity.id, ServiceAccountTokenSource(identity.encrypted_key, self.cipher)
        )
        return token.credentials()

    def audit(self, source, actor, action, target=None):
        self.session.add(
            AuditLog(
                organization_id=source.organization_id,
                actor_user_id=actor,
                action=action,
                target_type="drive_folder_link" if target else "data_source",
                target_id=target or source.id,
            )
        )

    def enable(self, *, scope, user_id):
        """Idempotent per organization. Returns a ready source (warm/free robot) or a
        `provisioning` one; `self.needs_provisioning` tells the caller to queue the worker task."""
        self.require_admin(scope=scope, user_id=user_id)
        self.needs_provisioning = False
        self.needs_labeling = None
        # Serialize concurrent enables for one tenant, then SKIP LOCKED across the pool.
        self.session.scalar(
            select(Organization).where(Organization.id == scope.organization_id).with_for_update()
        )
        source = self.session.scalar(
            select(DataSource).where(
                DataSource.organization_id == scope.organization_id,
                DataSource.provider == self.provider,
            )
        )
        if source:
            if source.status == "disconnected":
                return self._reenable(source, scope, user_id)
            if source.status == PROVISIONING_FAILED:
                source.status = PROVISIONING  # explicit user retry
                self.needs_provisioning = True
            return source
        identity = self._claim_free_robot(scope.organization_id)
        source = DataSource(
            organization_id=scope.organization_id,
            provider=self.provider,
            status="awaiting_share" if identity else PROVISIONING,
            sa_identity_id=identity.id if identity else None,
            connected_by_user_id=user_id,
            account_email=identity.sa_email if identity else None,
        )
        self.session.add(source)
        self.session.flush()
        self.needs_provisioning = identity is None
        self.audit(source, user_id, "drive_sa.enabled" if identity else "drive_sa.provisioning_requested")
        if identity:
            free = self.session.scalar(
                select(func.count())
                .select_from(GoogleSaIdentity)
                .where(GoogleSaIdentity.status == "free")
            )
            if free < 10 and not self.settings.google_sa_pool_project_list:
                logger.warning(
                    "robot pool low", extra={"event": "drive_sa.pool_low", "free_count": free}
                )
        return source

    def _claim_free_robot(self, organization_id):
        """Assign a free pool robot to the org (SKIP LOCKED); `None` means provisioning is needed."""
        identity = self.session.scalar(
            select(GoogleSaIdentity)
            .where(
                GoogleSaIdentity.status == "free",
                GoogleSaIdentity.organization_id.is_(None),
                GoogleSaIdentity.assigned_at.is_(None),
                GoogleSaIdentity.encrypted_key.is_not(None),
            )
            .order_by(GoogleSaIdentity.created_at, GoogleSaIdentity.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not identity and not self.settings.google_sa_pool_project_list:
            raise SaRequestError("pool_empty", 503)
        if identity:
            identity.organization_id = organization_id
            identity.status = "assigned"
            identity.assigned_at = datetime.now(UTC)
            self.needs_labeling = identity.id
        return identity

    def _reenable(self, source, scope, user_id):
        """Reconnect after disconnect: a NEW robot for the same source. The retired one is never touched again;
        old folder links stay unlinked, so the customer shares the folders again with the new robot."""
        previous = source.sa_identity_id
        identity = self._claim_free_robot(scope.organization_id)
        source.sa_identity_id = identity.id if identity else None
        source.account_email = identity.sa_email if identity else None
        source.status = "awaiting_share" if identity else PROVISIONING
        source.connected_by_user_id = user_id
        source.encrypted_credentials = None
        self.needs_provisioning = identity is None
        self.session.flush()
        for action, target in (
            ("drive_sa.reenabled" if identity else "drive_sa.reenable_requested", identity.id if identity else source.id),
            ("drive_sa.robot_replaced", previous),
        ):
            if target is None:
                continue
            self.session.add(
                AuditLog(
                    organization_id=source.organization_id,
                    actor_user_id=user_id,
                    action=action,
                    target_type="google_sa_identity" if target != source.id else "data_source",
                    target_id=target,
                )
            )
        return source

    def enable_status(self, source):
        if source.status == PROVISIONING:
            return {"status": "provisioning", "robot_email": None}
        if source.status == PROVISIONING_FAILED:
            return {"status": "failed", "robot_email": None}
        return {"status": "ready", "robot_email": source.account_email}

    def inbox(self, source):
        links = list(
            self.session.scalars(
                select(DriveFolderLink).where(
                    DriveFolderLink.organization_id == source.organization_id,
                    DriveFolderLink.data_source_id == source.id,
                    DriveFolderLink.status != "removed",
                )
            )
        )
        # Unlinked (purge_scheduled) or access_lost folders must reappear so they can be relinked.
        linked = {x.external_folder_id for x in links if x.status in ("verified", "suspect")}
        items = [
            x
            for x in self.client.inbox(credentials=self.credentials(source))
            if x.get("sharedWithMeTime")
        ]
        # Hierarchy known without extra Drive calls: shared folders + current links.
        known = {x["id"]: (x["name"], x.get("parents") or []) for x in items}
        for x in links:
            known.setdefault(x.external_folder_id, (x.folder_name, x.parent_external_ids or []))
        return [
            {
                "id": x["id"],
                "name": x["name"],
                "shared_by_email": x.get("sharingUser", {}).get("emailAddress"),
                "shared_at": x.get("sharedWithMeTime"),
                "linked": x["id"] in linked,
                "parent_ids": x.get("parents") or [],
                "nested_in": self._nested_in(x["id"], known, linked),
            }
            for x in items
        ]

    @staticmethod
    def _nested_in(folder_id, known, linked):
        """Nearest known ancestor (shared folder or link) of `folder_id`, `None` when it is a top-level share."""
        seen, current = {folder_id}, folder_id
        for _ in range(10):
            parents = known.get(current, ("", []))[1]
            if not parents or parents[0] in seen:
                return None
            current = parents[0]
            seen.add(current)
            if current in known:
                return {"id": current, "name": known[current][0], "linked": current in linked}
        return None

    def check_nested(self, source, root, chain=None):
        """Reject a folder whose ancestor is already a verified link (its files are already included)."""
        if chain is None:
            chain = self.client_ancestors(source, root)
        verified = {
            x.external_folder_id: x.folder_name for x in self.links(source) if x.status == "verified"
        }
        for ancestor in chain:
            if ancestor["id"] in verified and ancestor["id"] != root.get("id"):
                raise NestedInLinked(ancestor["id"], verified[ancestor["id"]])
        return chain

    SAMPLE_FILES = 3
    SAMPLE_MAX_BYTES = 10 * 1024 * 1024

    def verify(self, source, url_or_id, *, sample=True, count=True):
        """`count=False` is the link path: re-validates access only (ancestor chain), no listing."""
        try:
            folder_id = parse_folder_id(url_or_id)
        except ValueError:
            raise SaRequestError("invalid_folder_link") from None
        credentials = self.credentials(source)
        root, share = self.client.verify_folder(credentials=credentials, folder_id=folder_id)
        # The first files.list is strictly after files.get and explicit-share verification.
        files = (
            self.client.list_folder_files(
                credentials=credentials, root_folder_id=folder_id, root_verified=True
            )
            if count
            else []
        )
        blocked = sum(x.can_download is False for x in files)
        if sample and files:
            from concurrent.futures import ThreadPoolExecutor

            from app.ingestion.extraction import ELIGIBLE_MIME_TYPES
            from app.integrations.errors import SourceItemUnavailable

            candidates = [
                x
                for x in files
                if x.can_download is not False
                and x.mime_type in ELIGIBLE_MIME_TYPES
                and (x.size is None or x.size <= self.SAMPLE_MAX_BYTES)
            ][: self.SAMPLE_FILES]

            def probe(file):
                try:
                    with self.client.read_file(credentials=credentials, remote_file=file):
                        return 0
                except SourceItemUnavailable:
                    return 1

            if candidates:
                with ThreadPoolExecutor(max_workers=len(candidates)) as pool:
                    blocked += sum(pool.map(probe, candidates))
        return {
            "code": "download_blocked_partial" if blocked else "ok",
            "folder_id": folder_id,
            "name": root["name"],
            "shared_by_email": share.get("sharingUser", {}).get("emailAddress"),
            "shared_at": share.get("sharedWithMeTime"),
            "file_count": len(files),
            "blocked_download_count": blocked,
        }, root

    SPACE_DISCLOSURE_VERSION = "2026-10"

    def check_spaces(self, scope, space_ids):
        """Refuse before touching Drive: every Space must be a live Space of this organization."""
        if not space_ids:  # none or empty: the default Space (a folder is never left outside every Space)
            return None
        ids = list(dict.fromkeys(space_ids))
        if len(enrollment.valid_space_ids(self.session, scope.organization_id, ids)) != len(ids):
            raise SpaceNotFound("space not found")
        return ids

    def _grant_spaces(self, scope, user_id, link, space_ids):
        if space_ids is None or link.workspace_folder_id is None:
            return
        spaces = SpaceService(self.session)
        for space_id in space_ids:
            spaces.grant_folder(
                scope, user_id, space_id, link.workspace_folder_id, {"text_version": self.SPACE_DISCLOSURE_VERSION}
            )

    def link(self, *, scope, user_id, source_id, folder_id, space_ids=None):
        source = self.source(scope=scope, user_id=user_id, source_id=source_id)
        space_ids = self.check_spaces(scope, space_ids)
        # Serialize link creation against recheck and unlink in this source.
        self.session.scalar(select(DataSource).where(DataSource.id == source.id).with_for_update())
        data, root = self.verify(source, folder_id, sample=False, count=False)
        return self._connect(source, scope, user_id, data, root, space_ids=space_ids)

    def _connect(self, source, scope, user_id, data, root, *, blocked=None, chain=None, space_ids=None):
        link = self.session.scalar(
            select(DriveFolderLink).where(
                DriveFolderLink.organization_id == scope.organization_id,
                DriveFolderLink.external_folder_id == data["folder_id"],
            )
        )
        if link and link.status == "verified":
            self._grant_spaces(scope, user_id, link, space_ids)
            return link
        self.check_nested(source, root, chain)
        source.status = "connected"
        self.session.flush()  # select_scope re-reads the source; sessions run with autoflush=False
        folder = WorkspaceService(self.session).select_scope(
            scope=scope,
            user_id=user_id,
            source_id=source.id,
            requested=WorkspaceScope(mode="selected", folder_ids=(data["folder_id"],)),
            uniform_access_confirmed=True,
            available_folder_names={data["folder_id"]: data["name"]},
            space_ids=[] if space_ids is not None else None,  # explicit Spaces replace the default-Space grant
        )
        if not link:
            link = DriveFolderLink(
                organization_id=scope.organization_id,
                data_source_id=source.id,
                workspace_folder_id=folder.id,
                external_folder_id=data["folder_id"],
                folder_name=data["name"],
                is_shared_drive=bool(root.get("driveId")),
                created_by_user_id=user_id,
            )
            self.session.add(link)
        link.shared_by_email = data["shared_by_email"]
        link.shared_at = datetime.fromisoformat(data["shared_at"]) if data["shared_at"] else None
        link.parent_external_ids = list(root.get("parents") or [])
        if blocked is not None:
            link.blocked_download_count = blocked
        # verify (count=False) skips the listing; the blocked count was reported by the earlier verify call.
        self.restore(link)
        self.session.flush()
        self._grant_spaces(scope, user_id, link, space_ids)
        self.audit(source, user_id, "drive_sa.folder_linked", link.id)
        return link

    MAX_BATCH = 20

    def link_batch(self, *, scope, user_id, source_id, folder_ids, space_ids=None):
        """Verify + link several folders; one result per requested folder, a failure never aborts the rest."""
        source = self.source(scope=scope, user_id=user_id, source_id=source_id)
        space_ids = self.check_spaces(scope, space_ids)
        ids = list(dict.fromkeys(x.strip() for x in folder_ids if x and x.strip()))
        if not ids or len(ids) > self.MAX_BATCH:
            raise SaRequestError("invalid_request")
        self.session.scalar(select(DataSource).where(DataSource.id == source.id).with_for_update())
        results, ready, chains = {}, [], {}
        for folder_id in ids:
            try:
                data, root = self.verify(source, folder_id)
                chain = self.client_ancestors(source, root)
                chains[folder_id] = chain
                ready.append((len(chain), folder_id, data, root))
            except Exception as error:  # noqa: BLE001 - classified below, never leaks details
                results[folder_id] = self._failure(folder_id, error)
        # Shallowest first: if a selected folder holds another selected folder, the parent wins.
        for _, folder_id, data, root in sorted(ready, key=lambda x: x[0]):
            try:
                with self.session.begin_nested():
                    link = self._connect(
                        source,
                        scope,
                        user_id,
                        data,
                        root,
                        blocked=data["blocked_download_count"],
                        chain=chains[folder_id],
                        space_ids=space_ids,
                    )
                results[folder_id] = {
                    "folder_id": data["folder_id"],
                    "name": data["name"],
                    "status": "ok",
                    "code": data["code"],
                    "link_id": str(link.id),
                    "workspace_folder_id": str(link.workspace_folder_id),
                    "file_count": data["file_count"],
                    "blocked_download_count": data["blocked_download_count"],
                }
            except Exception as error:  # noqa: BLE001
                results[folder_id] = self._failure(folder_id, error, name=data["name"])
        return [results[x] for x in ids]

    def client_ancestors(self, source, root):
        ancestors = getattr(self.client, "ancestors", None)
        return ancestors(credentials=self.credentials(source), root=root) if ancestors else []

    @staticmethod
    def _failure(folder_id, error, *, name=None):
        import httpx
        import redis

        from app.integrations.http import RemoteThrottled

        extra = {}
        if isinstance(error, NestedInLinked):
            code = error.code
            extra = {"parent_id": error.parent_id, "parent_name": error.parent_name}
        elif isinstance(error, SaRequestError):
            code = error.code
        elif isinstance(error, FolderAccessLost):
            code = "not_shared"
        elif isinstance(error, RobotUnavailable):
            code = "robot_unavailable"
        elif isinstance(error, RemoteThrottled):
            code = "rate_limited"
        elif isinstance(error, (httpx.HTTPError, redis.RedisError)):
            code = "provider_unavailable"
        else:
            logger.warning("drive_sa batch folder failed", extra={"event": "drive_sa.batch_failed"})
            code = "provider_unavailable"
        return {
            "folder_id": folder_id,
            "name": name,
            "status": "nested" if code == "nested_in_linked" else "error",
            "code": code,
            **extra,
        }

    def linked_folders(self, source):
        return [
            RemoteFolder(x.external_folder_id, x.folder_name, tuple(x.parent_external_ids or ()))
            for x in self.links(source)
            if x.status == "verified"
        ]

    def links(self, source):
        return list(
            self.session.scalars(
                select(DriveFolderLink).where(
                    DriveFolderLink.organization_id == source.organization_id,
                    DriveFolderLink.data_source_id == source.id,
                )
            )
        )

    def affected_workspaces(self, link):
        # Includes user-created unions containing this explicit grant.
        return set(
            self.session.scalars(
                select(WorkspaceFolder.id)
                .join(
                    WorkspaceFolderSelection,
                    WorkspaceFolderSelection.workspace_folder_id == WorkspaceFolder.id,
                )
                .where(
                    WorkspaceFolder.organization_id == link.organization_id,
                    WorkspaceFolder.source_id == link.data_source_id,
                    WorkspaceFolderSelection.kind == "folder",
                    WorkspaceFolderSelection.external_folder_id == link.external_folder_id,
                )
            )
        )

    def hide(self, link):
        ids = self.affected_workspaces(link)
        self.session.execute(
            update(WorkspaceFolder).where(WorkspaceFolder.id.in_(ids)).values(status="access_lost")
        )
        self.session.execute(
            update(Document)
            .where(
                Document.organization_id == link.organization_id,
                Document.workspace_folder_id.in_(ids),
                Document.index_status == "indexed",
            )
            .values(index_status="access_lost")
        )
        self.session.flush()

    def mark_suspect(self, source, folder_id, *, now=None):
        now = now or datetime.now(UTC)
        self.session.scalar(select(DataSource).where(DataSource.id == source.id).with_for_update())
        self.session.flush()
        for link in self.links(source):
            self.session.refresh(link)
        targets = [
            x
            for x in self.links(source)
            if x.status in ("verified", "suspect", "access_lost")
            and (folder_id is None or x.external_folder_id == folder_id)
        ]
        for link in targets:
            if link.status == "verified":
                link.status = "suspect"
                link.suspect_since = now
                link.purge_after = now + timedelta(days=14)
                self.audit(
                    source, source.connected_by_user_id, "drive_sa.folder_access_suspect", link.id
                )
            elif link.status == "suspect" and now - utc(link.suspect_since) >= timedelta(hours=1):
                link.status = "access_lost"
                link.access_lost_at = now
                self.audit(
                    source, source.connected_by_user_id, "drive_sa.folder_access_lost", link.id
                )
                from app.notifications.models import Notification
                from app.organizations.models import Membership, MembershipRole

                admins = self.session.scalars(
                    select(Membership.user_id).where(
                        Membership.organization_id == source.organization_id,
                        Membership.is_active.is_(True),
                        Membership.role.in_([MembershipRole.OWNER, MembershipRole.ADMIN]),
                    )
                )
                # Notification fields follow the existing product model (metadata only).
                for admin in admins:
                    self.session.add(
                        Notification(
                            organization_id=source.organization_id,
                            user_id=admin,
                            kind="drive_access_lost",
                            title="Acesso à pasta removido",
                            body="Recompartilhe a pasta com o robô da empresa.",
                            data={"source_id": str(source.id), "link_id": str(link.id)},
                        )
                    )
            link.last_checked_at = now
            link.last_error_code = "not_shared"
            self.hide(link)
        self.session.flush()

    def restore(self, link):
        was_hidden = link.status != "verified"
        link.status = "verified"
        link.suspect_since = None
        link.access_lost_at = None
        link.purge_after = None
        link.last_error_code = None
        ids = self.affected_workspaces(link)
        # A union remains hidden until all its selected grants are verified.
        for workspace_id in ids:
            selected = set(
                self.session.scalars(
                    select(WorkspaceFolderSelection.external_folder_id).where(
                        WorkspaceFolderSelection.workspace_folder_id == workspace_id
                    )
                )
            )
            invalid = any(
                x.external_folder_id in selected and x.id != link.id and x.status != "verified"
                for x in self.session.scalars(
                    select(DriveFolderLink).where(
                        DriveFolderLink.data_source_id == link.data_source_id
                    )
                )
            )
            if invalid:
                continue
            folder = self.session.get(WorkspaceFolder, workspace_id)
            if was_hidden:
                folder.status = "not_synced"
            self.session.execute(
                update(Document)
                .where(
                    Document.organization_id == link.organization_id,
                    Document.workspace_folder_id == workspace_id,
                    Document.index_status == "access_lost",
                )
                .values(index_status="indexed")
            )
            if was_hidden:
                self.session.execute(
                    update(WorkspaceFolderSelection)
                    .where(WorkspaceFolderSelection.workspace_folder_id == workspace_id)
                    .values(encrypted_delta_link=None)
                )
        self.session.flush()

    def recheck(self, source, *, now=None):
        now = now or datetime.now(UTC)
        self.session.scalar(select(DataSource).where(DataSource.id == source.id).with_for_update())
        credentials = self.credentials(source)
        for link in self.links(source):
            if link.status in ("removed", "purge_scheduled"):
                continue
            try:
                self.client.verify_folder(
                    credentials=credentials, folder_id=link.external_folder_id
                )
            except FolderAccessLost:
                self.mark_suspect(source, link.external_folder_id, now=now)
            else:
                self.restore(link)
                link.last_checked_at = now
        source.status = (
            "connected"
            if any(x.status == "verified" for x in self.links(source))
            else "awaiting_share"
        )
        self.session.flush()
        return self.links(source)

    def unlink(self, *, scope, user_id, source_id, link_id, purge=False):
        source = self.source(scope=scope, user_id=user_id, source_id=source_id)
        self.session.scalar(select(DataSource).where(DataSource.id == source.id).with_for_update())
        link = self.session.scalar(
            select(DriveFolderLink).where(
                DriveFolderLink.id == link_id,
                DriveFolderLink.organization_id == scope.organization_id,
                DriveFolderLink.data_source_id == source.id,
            )
        )
        if not link:
            raise SaRequestError("not_shared", 404)
        self.hide(link)
        link.status = "purge_scheduled"
        deadline = datetime.now(UTC) + timedelta(days=14)
        link.purge_after = min(utc(link.purge_after), deadline) if link.purge_after else deadline
        if purge:
            self.purge(link)
        self.audit(source, user_id, "drive_sa.folder_unlinked", link.id)
        self.session.flush()
        return link

    def purge(self, link):
        ids = self.affected_workspaces(link)
        # Remove only catalog nodes in this root's subtree, never another root/tenant.
        nodes = list(
            self.session.scalars(
                select(LibraryNode).where(
                    LibraryNode.organization_id == link.organization_id,
                    LibraryNode.source_id == link.data_source_id,
                )
            )
        )
        remove = {x.id for x in nodes if x.external_id == link.external_folder_id}
        while True:
            additions = {x.id for x in nodes if x.parent_id in remove} - remove
            if not additions:
                break
            remove |= additions
        external_ids = {x.external_id for x in nodes if x.id in remove}
        single_scope_ids = set()
        for workspace_id in ids:
            selected = list(
                self.session.scalars(
                    select(WorkspaceFolderSelection.external_folder_id).where(
                        WorkspaceFolderSelection.workspace_folder_id == workspace_id
                    )
                )
            )
            if selected == [link.external_folder_id]:
                single_scope_ids.add(workspace_id)
        # For unions, delete only files below the revoked root. Other grants remain retained.
        from sqlalchemy import or_

        documents = list(
            self.session.scalars(
                select(Document.id).where(
                    Document.organization_id == link.organization_id,
                    Document.workspace_folder_id.in_(ids),
                    or_(
                        Document.workspace_folder_id.in_(single_scope_ids),
                        Document.external_file_id.in_(external_ids),
                    ),
                )
            )
        )
        self.session.execute(
            delete(DocumentChunk).where(
                DocumentChunk.organization_id == link.organization_id,
                DocumentChunk.document_id.in_(documents),
            )
        )
        self.session.execute(
            delete(Document).where(
                Document.organization_id == link.organization_id, Document.id.in_(documents)
            )
        )
        self.session.execute(delete(LibraryNode).where(LibraryNode.id.in_(remove)))
        for folder_id in ids:
            folder = self.session.get(WorkspaceFolder, folder_id)
            if folder:
                folder.status = "access_lost"
        link.status = "removed"
        link.purge_after = None
        self.session.flush()

    def purge_due(self, *, now=None):
        now = now or datetime.now(UTC)
        links = list(
            self.session.scalars(
                select(DriveFolderLink).where(
                    DriveFolderLink.purge_after <= now,
                    DriveFolderLink.status.in_(["access_lost", "purge_scheduled"]),
                )
            )
        )
        count = 0
        for link in links:
            if not self.settings.google_sa_enabled_for(link.organization_id):
                continue
            self.session.scalar(
                select(DataSource).where(DataSource.id == link.data_source_id).with_for_update()
            )
            self.session.refresh(link)
            if (
                link.status not in {"access_lost", "purge_scheduled"}
                or not link.purge_after
                or utc(link.purge_after) > now
            ):
                continue
            self.purge(link)
            count += 1
        return count

    def disconnect(self, *, scope, user_id, source_id):
        source = self.source(scope=scope, user_id=user_id, source_id=source_id)
        identity = self.identity(source)
        for link in self.links(source):
            if link.status != "removed":
                self.unlink(scope=scope, user_id=user_id, source_id=source_id, link_id=link.id)
        identity.status = "retired"
        identity.retired_at = datetime.now(UTC)
        # The runtime cannot call IAM. Local key erased immediately; IAM deletion is offline.
        identity.encrypted_key = None
        source.status = "disconnected"
        source.encrypted_credentials = None
        self.audit(source, user_id, "drive_sa.retired")
        self.session.flush()
        return source

    def rotate_key(self, source, *, user_id, new_key):
        self.require_admin(scope=OrganizationScope(source.organization_id), user_id=user_id)
        identity = self.identity(source)
        if new_key.get("client_email") != identity.sa_email:
            raise SaRequestError("invalid_robot_key")
        encrypted = self.cipher.encrypt(new_key)
        credentials = ServiceAccountTokenSource(encrypted, self.cipher).credentials()
        self.client.start_page_token(credentials=credentials)
        identity.encrypted_key = encrypted
        identity.key_version += 1
        identity.rotated_at = datetime.now(UTC)
        self._tokens.pop(identity.id, None)
        self.audit(source, user_id, "drive_sa.key_rotated")
        self.session.flush()
