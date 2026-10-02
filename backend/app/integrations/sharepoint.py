"""Microsoft 365 / SharePoint Online document libraries over delegated Microsoft Graph."""

from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from app.ingestion.extraction import limits
from app.ingestion.service import DiscoveryResult
from app.integrations.google_drive import RemoteFolder
from app.integrations.onedrive import (
    GRAPH_ROOT,
    DeltaPage,
    MicrosoftGraphClient,
    OneDriveConnectionService,
    OneDriveCredentials,
    OneDriveCursorInvalid,
    OneDriveDeltaExpired,
    OneDriveDocumentProvider,
    OneDriveOAuthInvalid,
)

# SharePoint does not exist for personal accounts; work/school only.
SHAREPOINT_AUTHORITY = "https://login.microsoftonline.com/organizations/oauth2/v2.0"
SHAREPOINT_SCOPES = "openid profile offline_access User.Read Sites.Read.All"
COMPOSITE_SEP = "|"
SITE_PREFIX = "site"
ITEM_SELECT = "id,name,size,file,folder,parentReference,webUrl,lastModifiedDateTime,deleted"


class SharePointIdInvalid(ValueError):
    pass


def composite_id(drive_id: str, item_id: str) -> str:
    if not drive_id or not item_id or COMPOSITE_SEP in drive_id or COMPOSITE_SEP in item_id:
        raise SharePointIdInvalid("invalid SharePoint identifier")
    return f"{drive_id}{COMPOSITE_SEP}{item_id}"


def is_site_node(value: str) -> bool:
    return value.startswith(f"{SITE_PREFIX}{COMPOSITE_SEP}")


def site_node_id(site_id: str) -> str:
    return f"{SITE_PREFIX}{COMPOSITE_SEP}{site_id}"


def split_composite(value: str) -> tuple[str, str]:
    drive_id, sep, item_id = value.partition(COMPOSITE_SEP)
    if is_site_node(value) or not sep or not drive_id or not item_id or COMPOSITE_SEP in item_id:
        raise SharePointIdInvalid("invalid SharePoint identifier")
    return drive_id, item_id


def _drive(drive_id: str) -> str:
    return quote(drive_id, safe="")


class SharePointGraphClient(MicrosoftGraphClient):
    AUTHORITY = SHAREPOINT_AUTHORITY
    SCOPES = SHAREPOINT_SCOPES
    max_sites = 200

    @staticmethod
    def _external_id(item: dict[str, Any], *, fallback_drive_id: str | None = None) -> str:
        parent = item.get("parentReference") or {}
        return composite_id(
            str(parent.get("driveId") or fallback_drive_id or ""), str(item.get("id") or "")
        )

    @staticmethod
    def _parent_ids(parent: dict[str, Any]) -> tuple[str, ...]:
        drive_id, parent_id = parent.get("driveId"), parent.get("id")
        return (composite_id(str(drive_id), str(parent_id)),) if drive_id and parent_id else ()

    def tenant_hostname(self, *, credentials: OneDriveCredentials) -> str:
        data = self._get_json(
            f"{GRAPH_ROOT}/sites/root?$select=siteCollection", credentials=credentials
        )
        hostname = (data.get("siteCollection") or {}).get("hostname")
        if not isinstance(hostname, str) or not hostname:
            raise OneDriveOAuthInvalid("Microsoft tenant response is invalid")
        return hostname.lower()

    def _sites(self, credentials: OneDriveCredentials) -> list[dict[str, Any]]:
        rows = self._all_pages(
            f"{GRAPH_ROOT}/sites?search=*&$select=id,displayName,webUrl", credentials=credentials
        )
        unique: dict[str, dict[str, Any]] = {}
        for row in rows:
            if row.get("id"):
                unique.setdefault(str(row["id"]), row)
        return list(unique.values())

    def catalog(
        self, *, credentials: OneDriveCredentials, max_sites: int | None = None
    ) -> list[RemoteFolder]:
        nodes: list[RemoteFolder] = []
        for site in self._sites(credentials)[: max_sites or self.max_sites]:
            site_id = str(site["id"])
            drives = [
                drive
                for drive in self._all_pages(
                    f"{GRAPH_ROOT}/sites/{quote(site_id, safe=',')}/drives?$select=id,name,driveType",
                    credentials=credentials,
                )
                if drive.get("driveType") == "documentLibrary" and drive.get("id")
            ]
            if not drives:
                continue
            node = site_node_id(site_id)
            nodes.append(RemoteFolder(node, str(site.get("displayName") or "Site"), ()))
            for drive in drives:
                drive_id = str(drive["id"])
                nodes.append(
                    RemoteFolder(
                        composite_id(
                            drive_id,
                            self.drive_root_id(credentials=credentials, drive_id=drive_id),
                        ),
                        str(drive.get("name") or "Documentos"),
                        (node,),
                    )
                )
        return nodes

    def drive_root_id(self, *, credentials: OneDriveCredentials, drive_id: str) -> str:
        root = self._get_json(
            f"{GRAPH_ROOT}/drives/{_drive(drive_id)}/root?$select=id",
            credentials=credentials,
        )
        return str(root.get("id") or "")

    def list_folders(self, *, credentials, drive_id: str) -> list[dict[str, Any]]:
        pending = [self.drive_root_id(credentials=credentials, drive_id=drive_id)]
        visited: set[str] = set()
        folders: list[dict[str, Any]] = []
        while pending:
            parent = pending.pop()
            if not parent or parent in visited:
                continue
            visited.add(parent)
            url = (
                f"{GRAPH_ROOT}/drives/{_drive(drive_id)}/items/{quote(parent, safe='')}"
                f"/children?$select={ITEM_SELECT}&$top=200"
            )
            for item in self._all_pages(url, credentials=credentials):
                if isinstance(item.get("folder"), dict) and item.get("id"):
                    folders.append(item)
                    pending.append(str(item["id"]))
        return folders

    def list_files(self, *, credentials, scope_id: str) -> list[dict[str, Any]]:
        drive_id, root_item = split_composite(scope_id)
        pending, visited, files = [root_item], set(), {}
        while pending:
            parent = pending.pop()
            if parent in visited:
                continue
            visited.add(parent)
            url = f"{GRAPH_ROOT}/drives/{_drive(drive_id)}/items/{quote(parent, safe='')}/children?$select={ITEM_SELECT}&$top=200"
            for item in self._all_pages(url, credentials=credentials):
                if isinstance(item.get("folder"), dict):
                    pending.append(str(item.get("id") or ""))
                elif "file" in item:
                    files[self._external_id(item, fallback_drive_id=drive_id)] = item
        return list(files.values())

    def latest_delta_link(self, *, credentials, drive_id: str) -> str:
        data = self._get_json(
            f"{GRAPH_ROOT}/drives/{_drive(drive_id)}/root/delta?token=latest",
            credentials=credentials,
        )
        link = data.get("@odata.deltaLink")
        if not isinstance(link, str):
            raise OneDriveOAuthInvalid("Microsoft delta response is invalid")
        return self._validate_graph_url(link)

    def delta_root(self, *, credentials, drive_id: str, cursor: str | None) -> DeltaPage:
        url = cursor or f"{GRAPH_ROOT}/drives/{_drive(drive_id)}/root/delta?$select={ITEM_SELECT}"
        items: list[dict[str, Any]] = []
        while url:
            data = self._get_json(url, credentials=credentials, allow_expired_delta=True)
            items.extend(i for i in data.get("value") or [] if isinstance(i, dict))
            if isinstance(data.get("@odata.nextLink"), str):
                url = self._validate_graph_url(data["@odata.nextLink"])
            elif isinstance(data.get("@odata.deltaLink"), str):
                return DeltaPage(items, self._validate_graph_url(data["@odata.deltaLink"]))
            else:
                raise OneDriveOAuthInvalid("Microsoft delta response is incomplete")
        raise OneDriveOAuthInvalid("Microsoft delta response is incomplete")

    def get_item(self, *, credentials, item_id: str) -> dict[str, Any] | None:
        drive_id, raw = split_composite(item_id)
        return self._get_or_none(
            f"{GRAPH_ROOT}/drives/{_drive(drive_id)}/items/{quote(raw, safe='')}?$select={ITEM_SELECT}",
            credentials,
        )

    def _get_or_none(self, url: str, credentials) -> dict[str, Any] | None:
        try:
            return self._get_json(url, credentials=credentials)
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 404:
                return None
            raise

    def within_scope(
        self,
        *,
        credentials,
        drive_id: str,
        parent_id: str,
        scope_item_id: str,
        cache: dict[str, bool],
        drive_root_id: str | None = None,
    ) -> bool:
        chain, current, result = [], parent_id, False
        for _ in range(64):  # depth guard against cycles
            if not current:
                break
            if current in cache:
                result = cache[current]
                break
            if current == scope_item_id:
                result = True
                break
            if current == drive_root_id:
                break
            chain.append(current)
            data = self._get_or_none(
                f"{GRAPH_ROOT}/drives/{_drive(drive_id)}/items/{quote(current, safe='')}?$select=id,parentReference",
                credentials,
            )
            current = str(((data or {}).get("parentReference") or {}).get("id") or "")
        for node in chain:
            cache[node] = result
        return result

    def read_file(self, *, credentials, item_id: str, size=None, hashes=None):
        drive_id, raw = split_composite(item_id)
        return self._download(
            f"{GRAPH_ROOT}/drives/{_drive(drive_id)}/items/{quote(raw, safe='')}/content",
            credentials, size=size, hashes=hashes,
        )


class SharePointDocumentProvider(OneDriveDocumentProvider):
    """Library/folder scopes over per-library root delta plus a membership filter."""

    key = "sharepoint"
    max_workers = 2
    max_file_bytes = limits.MAX_FILE_BYTES

    def folders(self, *, encrypted_credentials: str | None) -> list[RemoteFolder]:
        return self.client.catalog(credentials=self._credentials(encrypted_credentials))

    def folders_for_selections(
        self, *, encrypted_credentials: str | None, selections
    ) -> list[RemoteFolder]:
        credentials = self._credentials(encrypted_credentials)
        wanted = {split_composite(s.external_folder_id)[0] for s in selections}
        catalog = self.client.catalog(credentials=credentials)
        libraries = [
            node
            for node in catalog
            if not is_site_node(node.id) and split_composite(node.id)[0] in wanted
        ]
        sites = {parent for node in libraries for parent in node.parent_ids}
        nodes = [node for node in catalog if node.id in sites] + libraries
        for drive_id in sorted(wanted):
            for item in self.client.list_folders(credentials=credentials, drive_id=drive_id):
                nodes.append(
                    RemoteFolder(
                        self.client._external_id(item, fallback_drive_id=drive_id),
                        str(item.get("name") or "Untitled"),
                        self.client._parent_ids(item.get("parentReference") or {}),
                    )
                )
        return nodes

    def _in_scope(self, credentials, selection, item, root_id, cache) -> bool:
        _, scope_item = split_composite(selection.external_folder_id)
        if scope_item == root_id or item.get("id") == scope_item:
            return True
        return self.client.within_scope(
            credentials=credentials,
            drive_id=split_composite(selection.external_folder_id)[0],
            parent_id=str((item.get("parentReference") or {}).get("id") or ""),
            scope_item_id=scope_item,
            drive_root_id=root_id,
            cache=cache,
        )

    def discover(
        self,
        *,
        encrypted_credentials: str | None,
        selections,
        force_file_ids: set[str] | None = None,
        force_full: bool = False,
        progress_callback=None,
    ) -> DiscoveryResult:
        credentials = self._credentials(encrypted_credentials)
        changes: dict[str, dict[str, Any]] = {}
        removals: set[str] = set()
        links: dict[UUID, str | None] = {}
        roots: dict[str, str] = {}
        caches: dict[UUID, dict[str, bool]] = {}

        def root_of(drive_id: str) -> str:
            if drive_id not in roots:
                roots[drive_id] = self.client.drive_root_id(
                    credentials=credentials, drive_id=drive_id
                )
            return roots[drive_id]

        snapshot = force_full or any(not s.encrypted_delta_link for s in selections)
        if not snapshot:
            try:
                for selection in selections:
                    drive_id, _ = split_composite(selection.external_folder_id)
                    page = self.client.delta_root(
                        credentials=credentials,
                        drive_id=drive_id,
                        cursor=self.cipher.decrypt_cursor(selection.encrypted_delta_link),
                    )
                    links[selection.id] = page.delta_link
                    cache = caches.setdefault(selection.id, {})
                    sel_changes: dict[str, dict[str, Any]] = {}
                    sel_removals: set[str] = set()
                    for item in page.items:
                        ext = self.client._external_id(item, fallback_drive_id=drive_id)
                        if "deleted" in item:
                            sel_changes.pop(ext, None)
                            sel_removals.add(ext)
                            snapshot = snapshot or isinstance(item.get("folder"), dict)
                            continue
                        inside = self._in_scope(
                            credentials, selection, item, root_of(drive_id), cache
                        )
                        if isinstance(item.get("folder"), dict):
                            # Delta does not return descendants of a moved/renamed folder.
                            snapshot = snapshot or inside
                        elif "file" in item and inside:
                            sel_removals.discard(ext)
                            sel_changes[ext] = item
                        elif "file" in item:
                            sel_changes.pop(ext, None)
                            sel_removals.add(ext)
                    changes.update(sel_changes)
                    removals.update(sel_removals)
                    removals.difference_update(changes)
            except (OneDriveCursorInvalid, OneDriveDeltaExpired):
                snapshot = True
        if snapshot:
            files: dict[str, dict[str, Any]] = {}
            links = {}
            for selection in selections:
                drive_id, _ = split_composite(selection.external_folder_id)
                # Take the checkpoint first: changes during the walk reappear next delta.
                links[selection.id] = self.client.latest_delta_link(
                    credentials=credentials, drive_id=drive_id
                )
                for item in self.client.list_files(
                    credentials=credentials, scope_id=selection.external_folder_id
                ):
                    files[self.client._external_id(item, fallback_drive_id=drive_id)] = item
            changes, removals = files, set()
        for ext in sorted((force_file_ids or set()) - set(changes) - removals):
            item = self.client.get_item(credentials=credentials, item_id=ext)
            drive_id, _ = split_composite(ext)
            if (
                item is not None
                and "file" in item
                and any(
                    split_composite(s.external_folder_id)[0] == drive_id
                    and self._in_scope(
                        credentials, s, item, root_of(drive_id), caches.setdefault(s.id, {})
                    )
                    for s in selections
                )
            ):
                changes[ext] = item
            else:
                removals.add(ext)
        return DiscoveryResult(
            documents=self._read_changed(credentials, changes, progress_callback),
            removed_file_ids=tuple(sorted(removals)),
            delta_links=links,
            full_snapshot=snapshot,
        )


class SharePointConnectionService(OneDriveConnectionService):
    """Delegated OAuth bound to one Microsoft 365 tenant (SharePoint hostname)."""

    provider = "sharepoint"
    document_provider = SharePointDocumentProvider

    def bind_identity(self, credentials: OneDriveCredentials) -> str:
        return self.client.tenant_hostname(credentials=credentials)
