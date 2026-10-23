"""ClickUp OAuth and API adapter: tasks and Docs as read-only knowledge (ADR-0019).

The single write, `ClickUpOAuthClient.create_task`, is a human-approved action (ADR-0020).
"""

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_usage.models import AuditLog
from app.core.scoping import OrganizationScope
from app.ingestion.service import DiscoveredDocument, DiscoveryResult
from app.integrations.credentials import OAuthCredentials
from app.integrations.errors import SourceItemUnavailable, SourceRemoteUnauthorized
from app.integrations.google_drive import RemoteFolder
from app.integrations.http import (
    RemoteHttp,
    RemoteThrottled,
    parse_rate_limit_reset,
    parse_retry_after,
)
from app.integrations.models import DataSource
from app.integrations.oauth_base import OAuthConnectionServiceBase
from app.entitlements.service import require_source_quota

CLICKUP_API = "https://api.clickup.com"
# 100 requests/minute/token on Free, Unlimited and Business plans: stay below it.
CLICKUP_REQUEST_INTERVAL_SECONDS = 0.7
CLICKUP_PROCESSING_VERSION = "v1:clickup-v1"
WORKSPACE_PREFIX = "clickup:workspace:"
SPACE_PREFIX = "clickup:space:"
FOLDER_PREFIX = "clickup:folder:"
LIST_PREFIX = "clickup:list:"
TASK_PREFIX = "clickup:task:"
DOC_PREFIX = "clickup:doc:"
# Docs API v3 parent.type values (ClickUp reference, "Create a Doc").
_DOC_PARENT_PREFIX = {4: SPACE_PREFIX, 5: FOLDER_PREFIX, 6: LIST_PREFIX, 7: WORKSPACE_PREFIX, 12: WORKSPACE_PREFIX}
# Custom-field types whose value is plain text/number; drop_down and labels resolve option names.
_SIMPLE_FIELD_TYPES = {"short_text", "text", "number", "currency", "url", "email", "phone", "emoji"}
MAX_CUSTOM_FIELD_CHARS = 500
# Incremental sync (ADR-0019 D8): tasks are fetched with date_updated_gt = checkpoint - margin.
# The margin absorbs clock skew between us and ClickUp and edits made while a run was reading.
INCREMENTAL_CLOCK_MARGIN = timedelta(minutes=5)
# The task API cannot list what disappeared (deleted, archived, closed, moved out of scope), so a
# complete walk reconciles removals at least this often; runs in between only fetch the delta.
FULL_RECONCILE_INTERVAL = timedelta(hours=24)
CURSOR_VERSION = 1


class ClickUpRemoteUnauthorized(SourceRemoteUnauthorized):
    pass


class ClickUpOAuthUnavailable(RuntimeError):
    pass


class ClickUpOAuthInvalid(ValueError):
    pass


class ClickUpAccessDenied(PermissionError):
    pass


class ClickUpRateLimited(RuntimeError):
    """A write was refused with 429; nothing was created."""

    def __init__(self, retry_after_seconds: float | None = None):
        super().__init__("ClickUp rate limit reached")
        self.retry_after_seconds = retry_after_seconds


class ClickUpWriteRejected(ValueError):
    """ClickUp refused the payload (400/422); nothing was created."""


class ClickUpOutcomeUnknown(RuntimeError):
    """Timeout, transport or 5xx on a write: the task may or may not exist (never retried automatically)."""


def _utc_ms(value: object) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(str(value)) / 1000, UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


class ClickUpOAuthClient:
    def __init__(self, *, client_id: str | None, client_secret: str | None, redirect_uri: str | None,
                 http: RemoteHttp | None = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.http = http or RemoteHttp(min_interval_seconds=CLICKUP_REQUEST_INTERVAL_SECONDS)

    def _configured(self) -> None:
        if not self.client_id or not self.client_secret or not self.redirect_uri:
            raise ClickUpOAuthUnavailable("ClickUp OAuth is not configured")

    def authorization_url(self, *, state: str, scope: str = "") -> str:
        self._configured()
        return "https://app.clickup.com/api?" + urlencode(
            {"client_id": self.client_id, "redirect_uri": self.redirect_uri, "state": state}
        )

    def exchange_code(self, *, code: str) -> OAuthCredentials:
        self._configured()
        response = httpx.post(
            f"{CLICKUP_API}/api/v2/oauth/token",
            json={"client_id": self.client_id, "client_secret": self.client_secret, "code": code},
            timeout=15,
        )
        if response.status_code in {400, 401, 403}:
            raise ClickUpOAuthInvalid("ClickUp authorization failed")
        response.raise_for_status()
        # ClickUp tokens do not expire and have no refresh token (developer.clickup.com/docs/authentication).
        try:
            token = str(response.json()["access_token"])
        except (KeyError, TypeError, ValueError) as error:
            raise ClickUpOAuthInvalid("ClickUp authorization failed") from error
        return OAuthCredentials(access_token=token, refresh_token=None, expires_at=None)

    def account_email(self, *, credentials: OAuthCredentials) -> str | None:
        user = self._request("GET", "/api/v2/user", credentials=credentials).get("user") or {}
        email = user.get("email") if isinstance(user, dict) else None
        return email.strip().lower() if isinstance(email, str) and email.strip() else None

    def workspaces(self, *, credentials: OAuthCredentials) -> list[dict]:
        return self._items(self._request("GET", "/api/v2/team", credentials=credentials), "teams")

    def spaces(self, *, credentials: OAuthCredentials, workspace_id: str) -> list[dict]:
        return self._items(self._request(
            "GET", f"/api/v2/team/{workspace_id}/space", credentials=credentials,
            params={"archived": "false"}), "spaces")

    def folders(self, *, credentials: OAuthCredentials, space_id: str) -> list[dict]:
        return self._items(self._request(
            "GET", f"/api/v2/space/{space_id}/folder", credentials=credentials,
            params={"archived": "false"}), "folders")

    def folderless_lists(self, *, credentials: OAuthCredentials, space_id: str) -> list[dict]:
        return self._items(self._request(
            "GET", f"/api/v2/space/{space_id}/list", credentials=credentials,
            params={"archived": "false"}), "lists")

    def folder_lists(self, *, credentials: OAuthCredentials, folder_id: str) -> list[dict]:
        return self._items(self._request(
            "GET", f"/api/v2/folder/{folder_id}/list", credentials=credentials,
            params={"archived": "false"}), "lists")

    def list_tasks(self, *, credentials: OAuthCredentials, list_id: str, include_closed: bool,
                   date_updated_gt: int | None = None) -> list[dict]:
        tasks: list[dict] = []
        page = 0
        while True:
            params = {"page": str(page), "archived": "false", "subtasks": "true",
                      "include_closed": str(include_closed).lower(),
                      "include_markdown_description": "true"}
            if date_updated_gt is not None:  # Unix milliseconds
                params["date_updated_gt"] = str(date_updated_gt)
            data = self._request("GET", f"/api/v2/list/{list_id}/task", credentials=credentials, params=params)
            batch = self._items(data, "tasks")
            tasks.extend(batch)
            if data.get("last_page", True) is not False or not batch:
                return tasks
            page += 1

    def task(self, *, credentials: OAuthCredentials, task_id: str) -> dict:
        data = self._request("GET", f"/api/v2/task/{task_id}", credentials=credentials)
        return data if isinstance(data, dict) else {}

    def workspace_docs(self, *, credentials: OAuthCredentials, workspace_id: str) -> list[dict]:
        docs: list[dict] = []
        cursor: str | None = None
        while True:
            params = {"limit": "100", "deleted": "false", "archived": "false"}
            if cursor:
                params["cursor"] = cursor
            data = self._request("GET", f"/api/v3/workspaces/{workspace_id}/docs",
                                 credentials=credentials, params=params)
            docs.extend(self._items(data, "docs"))
            cursor = data.get("next_cursor") or None
            if not cursor:
                return docs

    def doc_pages(self, *, credentials: OAuthCredentials, workspace_id: str, doc_id: str) -> list[dict]:
        data = self._request(
            "GET", f"/api/v3/workspaces/{workspace_id}/docs/{doc_id}/pages", credentials=credentials,
            params={"max_page_depth": "-1", "content_format": "text/md"})
        return self._items(data, "pages")

    def list_members(self, *, credentials: OAuthCredentials, list_id: str) -> list[dict]:
        """People who can be assigned in the list (may be incomplete: guests and some plans are omitted)."""
        return self._items(self._request("GET", f"/api/v2/list/{list_id}/member", credentials=credentials), "members")

    def list_statuses(self, *, credentials: OAuthCredentials, list_id: str) -> list[dict]:
        data = self._request("GET", f"/api/v2/list/{list_id}", credentials=credentials)
        return self._items(data, "statuses")

    def create_task(self, *, credentials: OAuthCredentials, list_id: str, payload: dict) -> dict:
        """The only write of the connector (ADR-0020): human-approved, never called by the agent or MCP.

        Not retried by the HTTP core: a second POST after an unknown outcome would duplicate the task.
        """
        try:
            response = self.http.request(
                "POST", f"{CLICKUP_API}/api/v2/list/{list_id}/task", idempotent=False,
                headers={"Authorization": f"Bearer {credentials.access_token}"}, json=payload, timeout=20)
        except RemoteThrottled as error:
            raise ClickUpRateLimited(error.retry_after_seconds) from error
        except httpx.TransportError as error:
            raise ClickUpOutcomeUnknown("transport failure") from error
        status = response.status_code
        if status == 401:
            raise ClickUpRemoteUnauthorized()
        if status in {403, 404}:
            raise SourceItemUnavailable("restricted_resource" if status == 403 else "object_not_found")
        if status == 429:
            raise ClickUpRateLimited(
                parse_retry_after(response.headers.get("Retry-After"))
                or parse_rate_limit_reset(response.headers.get("X-RateLimit-Reset")))
        if status in {400, 422}:
            raise ClickUpWriteRejected("ClickUp rejected the task")
        if status >= 400:
            raise ClickUpOutcomeUnknown(f"http {status}")
        try:
            data = response.json()
        except ValueError as error:
            raise ClickUpOutcomeUnknown("unreadable response") from error
        if not isinstance(data, dict) or not data.get("id"):
            raise ClickUpOutcomeUnknown("response without task id")
        return data

    @staticmethod
    def _items(data: object, key: str) -> list[dict]:
        if isinstance(data, list):
            values = data
        else:
            values = data.get(key, []) if isinstance(data, dict) else []
        return [item for item in values if isinstance(item, dict)]

    def _request(self, method: str, path: str, *, credentials: OAuthCredentials, **kwargs: object):
        headers = {"Authorization": f"Bearer {credentials.access_token}"}
        response = self.http.request(method, f"{CLICKUP_API}{path}", headers=headers, timeout=20, **kwargs)
        if response.status_code == 401:
            raise ClickUpRemoteUnauthorized()
        if response.status_code in {403, 404}:
            raise SourceItemUnavailable("restricted_resource" if response.status_code == 403 else "object_not_found")
        response.raise_for_status()
        return response.json()


class ClickUpConnectionService(OAuthConnectionServiceBase):
    provider = "clickup"
    access_denied = ClickUpAccessDenied
    invalid = ClickUpOAuthInvalid

    def __init__(self, session: Session, cipher, client: ClickUpOAuthClient):
        super().__init__(session, cipher)
        self.client = client

    def begin(self, *, scope: OrganizationScope, user_id: UUID, session_secret: str,
              source_id: UUID | None = None) -> str:
        self.require_admin(scope=scope, user_id=user_id)
        if source_id is not None and self._own_source(
                organization_id=scope.organization_id, source_id=source_id) is None:
            raise ClickUpOAuthInvalid("ClickUp source is invalid")
        raw = self._new_state(scope=scope, user_id=user_id, session_secret=session_secret, source_id=source_id)
        return self.client.authorization_url(state=raw)

    def complete(self, *, raw_state: str, code: str, session_secret: str) -> DataSource:
        state = self._consume_state(raw_state=raw_state, session_secret=session_secret)
        credentials = self.client.exchange_code(code=code)
        try:
            account_email = self.client.account_email(credentials=credentials)
        except (SourceRemoteUnauthorized, SourceItemUnavailable) as error:
            raise ClickUpOAuthInvalid("ClickUp authorization failed") from error
        source = (
            self._own_source(organization_id=state.organization_id, source_id=state.source_id)
            if state.source_id else self.session.scalar(
                select(DataSource)
                .where(DataSource.organization_id == state.organization_id, DataSource.provider == "clickup")
                .order_by(DataSource.created_at.desc(), DataSource.id.desc())
            )
        )
        if state.source_id is not None and source is None:
            raise ClickUpOAuthInvalid("ClickUp source is invalid")
        if source is None:
            require_source_quota(self.session, state.organization_id, "clickup")
            source = DataSource(organization_id=state.organization_id, provider="clickup",
                                encrypted_credentials=self.cipher.encrypt(credentials), status="connected",
                                account_email=account_email, connected_by_user_id=state.user_id)
            self.session.add(source)
        else:
            source.encrypted_credentials = self.cipher.encrypt(credentials)
            source.status = "connected"
            source.account_email = account_email
            source.connected_by_user_id = state.user_id
        state.consumed_at = datetime.now(UTC)
        self.session.flush()
        self.session.add(AuditLog(organization_id=state.organization_id, actor_user_id=state.user_id,
                                  action="data_source.connected", target_type="data_source", target_id=source.id))
        self.session.flush()
        return source


@dataclass
class _Catalog:
    containers: dict[str, RemoteFolder]


class ClickUpDocumentProvider:
    key = "clickup"

    def __init__(self, client: ClickUpOAuthClient, cipher, *, include_closed_tasks: bool = False):
        self.client = client
        self.cipher = cipher
        self.include_closed_tasks = include_closed_tasks
        self._containers: dict[str, RemoteFolder] | None = None

    def _catalog(self, credentials: OAuthCredentials) -> _Catalog:
        containers: dict[str, RemoteFolder] = {}

        def add(prefix: str, item: dict, parent: str | None, kind: str) -> str | None:
            if not item.get("id") or item.get("archived") or item.get("deleted"):
                return None
            container_id = prefix + str(item["id"])
            containers[container_id] = RemoteFolder(
                container_id, str(item.get("name") or "Sem título"), (parent,) if parent else (), kind=kind)
            return container_id

        for workspace in self.client.workspaces(credentials=credentials):
            workspace_id = add(WORKSPACE_PREFIX, workspace, None, "workspace")
            if workspace_id is None:
                continue
            for space in self.client.spaces(credentials=credentials, workspace_id=str(workspace["id"])):
                space_id = add(SPACE_PREFIX, space, workspace_id, "space")
                if space_id is None:
                    continue
                raw_space_id = str(space["id"])
                for folder in self.client.folders(credentials=credentials, space_id=raw_space_id):
                    folder_id = add(FOLDER_PREFIX, folder, space_id, "folder")
                    if folder_id is None:
                        continue
                    lists = folder.get("lists")
                    if not isinstance(lists, list):
                        lists = self.client.folder_lists(credentials=credentials, folder_id=str(folder["id"]))
                    for item in lists:
                        if isinstance(item, dict):
                            add(LIST_PREFIX, item, folder_id, "list")
                for item in self.client.folderless_lists(credentials=credentials, space_id=raw_space_id):
                    add(LIST_PREFIX, item, space_id, "list")
        return _Catalog(containers)

    def folders(self, *, encrypted_credentials: str | None) -> list[RemoteFolder]:
        credentials = self.cipher.decrypt(encrypted_credentials or "")
        return list(self._catalog(credentials).containers.values())

    @staticmethod
    def _selected(containers: dict[str, RemoteFolder], selections) -> set[str]:
        if any(selection.kind == "all_accessible" for selection in selections):
            return set(containers)
        selected = {selection.external_folder_id for selection in selections if selection.kind == "folder"}
        selected &= set(containers)
        while added := {item.id for item in containers.values() if set(item.parent_ids) & selected} - selected:
            selected.update(added)
        return selected

    @staticmethod
    def _path(containers: dict[str, RemoteFolder], container_id: str) -> str:
        names: list[str] = []
        seen: set[str] = set()
        while container_id in containers and container_id not in seen:
            seen.add(container_id)
            folder = containers[container_id]
            names.append(folder.name)
            container_id = folder.parent_ids[0] if folder.parent_ids else ""
        return " > ".join(reversed(names))

    def folders_for_selections(self, *, encrypted_credentials, selections) -> list[RemoteFolder]:
        """Only selected containers and their ancestors are projected into the library.

        Names of Spaces/Lists the admin did not select must not become browsable
        by every member (there is no per-item ACL, ADR-0019 D3).
        """
        containers = self._containers
        if containers is None:
            containers = self._catalog(self.cipher.decrypt(encrypted_credentials or "")).containers
        keep = self._selected(containers, selections)
        pending = list(keep)
        while pending:
            for parent in containers[pending.pop()].parent_ids:
                if parent in containers and parent not in keep:
                    keep.add(parent)
                    pending.append(parent)
        return [containers[id] for id in sorted(keep)]

    def encrypt_delta_link(self, value: str) -> str:
        return self.cipher.encrypt_cursor(value)

    def _checkpoint(self, selections) -> tuple[datetime, datetime] | None:
        """(since, last complete walk) shared by every selection, or None when a full walk is needed.

        A missing, undecryptable, malformed or future-dated cursor on ANY selection means a
        full walk: the cursor of a selection added later must not hide its older tasks.
        """
        now = datetime.now(UTC)
        since: list[datetime] = []
        full_at: list[datetime] = []
        for selection in selections:
            token = getattr(selection, "encrypted_delta_link", None)
            if not token:
                return None
            try:
                data = json.loads(self.cipher.decrypt_cursor(token))
                if data["v"] != CURSOR_VERSION:
                    return None
                moments = _utc_ms(data["since"]), _utc_ms(data["full_at"])
            except Exception:  # noqa: BLE001 - any unreadable cursor degrades to a full walk
                return None
            if None in moments or moments[0] > now or moments[1] > now:
                return None
            since.append(moments[0])
            full_at.append(moments[1])
        return (min(since), min(full_at)) if since else None

    def discover(self, *, encrypted_credentials: str | None, selections, known_documents=None,
                 force_file_ids: set[str] | None = None, force_full: bool = False,
                 progress_callback=None) -> DiscoveryResult:
        started = datetime.now(UTC)  # taken before reading, so edits made during the run are re-read next time
        credentials = self.cipher.decrypt(encrypted_credentials or "")
        checkpoint = None if force_full or not known_documents else self._checkpoint(selections)
        # A task the last run failed to index (or that was asked to be rebuilt) would not be in a delta:
        # walk everything so it is retried.
        retrying = any(item.startswith(TASK_PREFIX) for item in force_file_ids or ())
        incremental = (checkpoint is not None and not retrying
                       and started - checkpoint[1] < FULL_RECONCILE_INTERVAL)
        task_floor = int((checkpoint[0] - INCREMENTAL_CLOCK_MARGIN).timestamp() * 1000) if incremental else None
        parent_names: dict[str, str] = {}
        containers = self._containers = self._catalog(credentials).containers
        selected = self._selected(containers, selections)
        known = known_documents or {}
        forced = force_file_ids or set()
        lists = sorted(id for id in selected if id.startswith(LIST_PREFIX))
        workspace_ids = sorted({self._workspace_of(containers, id) for id in selected} - {None})
        total = len(lists) + len(workspace_ids)
        done = 0
        # An unreadable area never proves a deletion, and it also forbids a full
        # snapshot (which removes every document missing from this run).
        tasks_unreadable = docs_unreadable = False
        seen: set[str] = set()
        changed: list[DiscoveredDocument] = []
        catalog: dict[str, DiscoveredDocument] = {}

        def unchanged(external_id: str, modified: datetime | None) -> bool:
            row = known.get(external_id)
            return bool(not force_full and row and row[1] in {"indexed", "skipped"}
                        and external_id not in forced and modified is not None
                        and _aware(row[0]) == modified)

        def collect(external_id: str, name: str, url: str, modified: datetime | None,
                    parent: str, text: str | None) -> None:
            if external_id in seen:  # one item belongs to a single container
                return
            seen.add(external_id)
            metadata = DiscoveredDocument(
                external_file_id=external_id, name=name, mime_type="text/markdown", source_url=url,
                modified_at=modified, parent_ids=(parent,), processing_version=CLICKUP_PROCESSING_VERSION)
            if text is None:  # unchanged (or unreadable) since the last indexed run
                if known[external_id][1] == "indexed":
                    catalog[external_id] = metadata
                return
            changed.append(replace(metadata, text=text))
            if text.strip():
                catalog[external_id] = metadata

        for list_id in lists:
            try:
                tasks = self.client.list_tasks(
                    credentials=credentials, list_id=list_id.removeprefix(LIST_PREFIX),
                    include_closed=self.include_closed_tasks,
                    **({"date_updated_gt": task_floor} if incremental else {}))
            except SourceItemUnavailable:
                tasks_unreadable = True
                tasks = []
            by_id = {str(task["id"]): task for task in tasks if task.get("id")}
            if incremental:  # a delta may hold a subtask without its parent: keep "Subtarefa de" stable
                self._resolve_parents(credentials, by_id, parent_names)
            path = self._path(containers, list_id)
            for task_id, task in by_id.items():
                external_id = TASK_PREFIX + task_id
                modified = _utc_ms(task.get("date_updated"))
                collect(external_id, str(task.get("name") or "Tarefa sem título"),
                        str(task.get("url") or f"https://app.clickup.com/t/{task_id}"), modified, list_id,
                        None if unchanged(external_id, modified) else _task_text(task, path, by_id | parent_names))
            done += 1
            if progress_callback:
                progress_callback(done, total)

        for workspace_id in workspace_ids:
            raw_workspace = workspace_id.removeprefix(WORKSPACE_PREFIX)
            try:
                docs = self.client.workspace_docs(credentials=credentials, workspace_id=raw_workspace)
            except SourceItemUnavailable:
                docs_unreadable = True  # Docs unavailable for this plan or token: tasks still sync
                docs = []
            for doc in docs:
                parent_id = self._doc_parent(doc, workspace_id, containers)
                if parent_id not in selected:
                    continue
                external_id = DOC_PREFIX + str(doc["id"])
                modified = _utc_ms(doc.get("date_updated"))
                name = str(doc.get("name") or "Doc sem título")
                url = f"https://app.clickup.com/{raw_workspace}/v/dc/{doc['id']}"
                text: str | None = None
                if not unchanged(external_id, modified):
                    try:
                        pages = self.client.doc_pages(credentials=credentials, workspace_id=raw_workspace,
                                                      doc_id=str(doc["id"]))
                    except SourceItemUnavailable:
                        docs_unreadable = True
                        if external_id in known:  # keep what is indexed; never delete on a failed read
                            collect(external_id, name, url, modified, parent_id, None)
                        else:
                            seen.add(external_id)
                        continue
                    text = _doc_text(name, pages)
                collect(external_id, name, url, modified, parent_id, text)
            done += 1
            if progress_callback:
                progress_callback(done, total)

        # A delta of tasks proves nothing about absent ones: only Docs (always listed in full) can
        # be removed on an incremental run; tasks wait for the next complete walk.
        removable = {item for item in set(known) - seen
                     if not (item.startswith(TASK_PREFIX) and (tasks_unreadable or incremental))
                     and not (item.startswith(DOC_PREFIX) and docs_unreadable)}
        # The checkpoint only advances over a fully readable run; otherwise the old one stays.
        cursor = None
        if not (tasks_unreadable or docs_unreadable):
            full_at = checkpoint[1] if incremental else started
            cursor = json.dumps({"v": CURSOR_VERSION, "since": int(started.timestamp() * 1000),
                                 "full_at": int(full_at.timestamp() * 1000)})
        return DiscoveryResult(
            documents=sorted(changed, key=lambda item: item.external_file_id),
            removed_file_ids=tuple(sorted(removable)),
            full_snapshot=(not known or force_full) and not (tasks_unreadable or docs_unreadable),
            catalog_documents=(None if incremental else
                               sorted(catalog.values(), key=lambda item: item.external_file_id)),
            delta_links=({selection.id: cursor for selection in selections}
                         if cursor is not None and all(hasattr(item, "id") for item in selections) else None),
        )

    def _resolve_parents(self, credentials, by_id: dict[str, dict], names: dict[str, dict]) -> None:
        for task in list(by_id.values()):
            parent = str(task.get("parent") or "")
            if not parent or parent in by_id or parent in names:
                continue
            try:
                names[parent] = self.client.task(credentials=credentials, task_id=parent)
            except SourceItemUnavailable:
                names[parent] = {}

    @staticmethod
    def _doc_parent(doc: dict, workspace_id: str, containers: dict[str, RemoteFolder]) -> str:
        """Container of a Doc; an unknown or malformed parent falls back to its Workspace (ADR-0019 D4)."""
        parent = doc.get("parent") if isinstance(doc.get("parent"), dict) else {}
        try:
            prefix = _DOC_PARENT_PREFIX.get(int(parent.get("type")))
        except (TypeError, ValueError):
            prefix = None
        candidate = prefix + str(parent["id"]) if prefix and prefix != WORKSPACE_PREFIX and parent.get("id") else None
        return candidate if candidate in containers else workspace_id

    @staticmethod
    def _workspace_of(containers: dict[str, RemoteFolder], container_id: str) -> str | None:
        seen: set[str] = set()
        while container_id in containers and container_id not in seen:
            seen.add(container_id)
            if container_id.startswith(WORKSPACE_PREFIX):
                return container_id
            parents = containers[container_id].parent_ids
            container_id = parents[0] if parents else ""
        return None


def _name_of(value: object, key: str) -> str:
    return str(value.get(key) or "") if isinstance(value, dict) else ""


def _custom_field_text(field: dict) -> str:
    kind, value = field.get("type"), field.get("value")
    if value in (None, "", []):
        return ""
    options = (field.get("type_config") or {}).get("options") or []
    if kind in _SIMPLE_FIELD_TYPES:
        text = str(value)
    elif kind == "drop_down":
        text = next((str(option.get("name")) for option in options
                     if isinstance(option, dict) and option.get("orderindex") == value), "")
    elif kind == "labels" and isinstance(value, list):
        names = {option.get("id"): option.get("label") for option in options if isinstance(option, dict)}
        text = ", ".join(str(names[item]) for item in value if item in names)
    elif kind == "date":
        moment = _utc_ms(value)
        text = moment.date().isoformat() if moment else ""
    else:
        return ""
    return text[:MAX_CUSTOM_FIELD_CHARS]


def _task_text(task: dict, path: str, siblings: dict[str, dict]) -> str:
    """Searchable Markdown for one task; attachments and comments are out of scope (ADR-0019)."""
    header = [f"# {task.get('name') or 'Tarefa sem título'}"]
    facts = [("Lista", path), ("Status", _name_of(task.get("status"), "status")),
             ("Prioridade", _name_of(task.get("priority"), "priority")),
             ("Responsáveis", ", ".join(
                 str(item.get("username") or item.get("email") or "")
                 for item in task.get("assignees") or [] if isinstance(item, dict)).strip(", ")),
             ("Etiquetas", ", ".join(
                 str(item.get("name")) for item in task.get("tags") or [] if isinstance(item, dict) and item.get("name")))]
    due = _utc_ms(task.get("due_date"))
    if due:
        facts.append(("Vencimento", due.date().isoformat()))
    parent = task.get("parent")
    if parent:
        parent_name = _name_of(siblings.get(str(parent)), "name")
        facts.append(("Subtarefa de", parent_name or str(parent)))
    for field in task.get("custom_fields") or []:
        if isinstance(field, dict) and field.get("name") and (text := _custom_field_text(field)):
            facts.append((str(field["name"]), text))
    lines = [f"{label}: {value}" for label, value in facts if value]
    body = str(task.get("markdown_description") or task.get("text_content") or task.get("description") or "").strip()
    return "\n\n".join(part for part in ("\n".join(header + lines), body) if part)


def _doc_text(name: str, pages: list[dict], depth: int = 1) -> str:
    sections = [f"# {name}"] if depth == 1 else []
    for page in pages:
        title = str(page.get("name") or "").strip()
        content = str(page.get("content") or "").strip()
        if title or content:
            sections.append("\n\n".join(part for part in (f"{'#' * min(depth + 1, 6)} {title}" if title else "", content) if part))
        children = page.get("pages")
        if isinstance(children, list) and children:
            nested = _doc_text(name, [child for child in children if isinstance(child, dict)], depth + 1)
            if nested:
                sections.append(nested)
    body = "\n\n".join(sections)
    # A Doc with a title but no page content is empty, not a one-line document.
    return body if len(sections) > (1 if depth == 1 else 0) else ""
