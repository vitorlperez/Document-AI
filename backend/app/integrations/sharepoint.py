"""Microsoft 365 / SharePoint Online document libraries over delegated Microsoft Graph."""

from typing import Any
from urllib.parse import quote

import httpx

from app.integrations.google_drive import RemoteFolder
from app.integrations.onedrive import (
    GRAPH_ROOT,
    DeltaPage,
    MicrosoftGraphClient,
    OneDriveCredentials,
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
        self, *, credentials: OneDriveCredentials, max_sites: int = 200
    ) -> list[RemoteFolder]:
        nodes: list[RemoteFolder] = []
        for site in self._sites(credentials)[:max_sites]:
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
                root = self._get_json(
                    f"{GRAPH_ROOT}/drives/{_drive(drive_id)}/root?$select=id",
                    credentials=credentials,
                )
                nodes.append(
                    RemoteFolder(
                        composite_id(drive_id, str(root.get("id") or "")),
                        str(drive.get("name") or "Documentos"),
                        (node,),
                    )
                )
        return nodes

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

    def read_file(self, *, credentials, item_id: str) -> bytes:
        drive_id, raw = split_composite(item_id)
        return self._download(
            f"{GRAPH_ROOT}/drives/{_drive(drive_id)}/items/{quote(raw, safe='')}/content",
            credentials,
        )
