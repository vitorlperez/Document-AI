"""Notion OAuth and API adapter."""

import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from urllib.parse import urlencode
from uuid import UUID

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.audit_usage.models import AuditLog
from app.core.scoping import OrganizationScope
from app.ingestion.service import DiscoveryResult
from app.integrations.credentials import OAuthCredentials
from app.integrations.errors import SourceItemUnavailable, SourceRemoteUnauthorized
from app.integrations.google_drive import RemoteFolder
from app.integrations.http import RemoteHttp
from app.integrations.models import DataSource, OAuthConnectionState
from app.integrations.oauth_base import OAuthConnectionServiceBase


class NotionRemoteUnauthorized(SourceRemoteUnauthorized):
    pass


NOTION_READ_SCOPE = ""
MAX_PAGE_WORKERS = 2
NOTION_REQUEST_INTERVAL_SECONDS = 0.35
NOTION_CONTAINER_PREFIX = "notion:container:"
NOTION_API_VERSION = "2025-09-03"


def notion_item_id(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError:
        return value


def notion_scope_id(value: str) -> str:
    return value.removeprefix(NOTION_CONTAINER_PREFIX)


def _rich_text(values: object) -> str:
    if not isinstance(values, list):
        return ""
    return "".join(str(item.get("plain_text") or (item.get("text") or {}).get("content") or "")
                   for item in values if isinstance(item, dict))


def _property_text(prop: dict) -> str:
    kind = prop.get("type")
    value = prop.get(kind)
    if kind == "rich_text":
        return _rich_text(value)
    if kind in {"select", "status"} and isinstance(value, dict):
        return str(value.get("name") or "")
    if kind in {"multi_select", "people", "files"} and isinstance(value, list):
        return ", ".join(str(item.get("name") or "") for item in value if isinstance(item, dict))
    if kind == "date" and isinstance(value, dict):
        return " — ".join(str(value[key]) for key in ("start", "end") if value.get(key))
    if kind in {"formula", "rollup"} and isinstance(value, dict):
        return _property_text(value)
    if kind == "relation" and isinstance(value, list):
        text = ", ".join(f"https://www.notion.so/{str(item['id']).replace('-', '')}"
                         for item in value if isinstance(item, dict) and item.get("id"))
        return text + (" (referências adicionais no Notion)" if prop.get("has_more") else "")
    if kind in {"number", "checkbox", "boolean", "url", "email", "phone_number", "string", "created_time", "last_edited_time"}:
        return str(value) if value is not None else ""
    return ""


class NotionOAuthUnavailable(RuntimeError):
    pass


class NotionOAuthInvalid(ValueError):
    pass


class NotionAccessDenied(PermissionError):
    pass


@dataclass(frozen=True)
class NotionPage:
    id: str
    title: str
    url: str
    last_edited_time: datetime | None
    parent_ids: tuple[str, ...] = ()
    parent_type: str | None = None
    object_type: str = "page"
    properties_text: str = ""
    data_source_ids: tuple[str, ...] = ()


class NotionOAuthClient:
    def __init__(self, *, client_id: str | None, client_secret: str | None, redirect_uri: str | None, http: RemoteHttp | None = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.http = http or RemoteHttp(min_interval_seconds=NOTION_REQUEST_INTERVAL_SECONDS)

    def _configured(self) -> None:
        if not self.client_id or not self.client_secret or not self.redirect_uri:
            raise NotionOAuthUnavailable("Notion OAuth is not configured")

    def authorization_url(self, *, state: str, scope: str = NOTION_READ_SCOPE) -> str:
        self._configured()
        return "https://api.notion.com/v1/oauth/authorize?" + urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "owner": "user",
                "state": state,
            }
        )

    def exchange_code(self, *, code: str) -> OAuthCredentials:
        self._configured()
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        response = httpx.post(
            "https://api.notion.com/v1/oauth/token",
            json={"grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri},
            headers={"Authorization": f"Basic {basic}", "Content-Type": "application/json"},
            timeout=15,
        )
        if response.status_code in {400, 401, 403}:
            raise NotionOAuthInvalid("Notion authorization failed")
        response.raise_for_status()
        data = response.json()
        return OAuthCredentials(access_token=str(data["access_token"]), refresh_token=None, expires_at=None)

    def account_email(self, *, credentials: OAuthCredentials) -> str | None:
        response = self._request("GET", "/v1/users/me", credentials=credentials)
        person = response.get("person") or {}
        email = person.get("email") if isinstance(person, dict) else None
        if not isinstance(email, str):
            bot = response.get("bot") or {}
            owner = bot.get("owner") if isinstance(bot, dict) else None
            owner_user = owner.get("user") if isinstance(owner, dict) else None
            owner_person = owner_user.get("person") if isinstance(owner_user, dict) else None
            email = owner_person.get("email") if isinstance(owner_person, dict) else None
        return str(email).strip().lower() if isinstance(email, str) and email.strip() else None

    def list_pages(self, *, credentials: OAuthCredentials) -> list[NotionPage]:
        return self._search(credentials=credentials, object_type="page")

    def list_databases(self, *, credentials: OAuthCredentials) -> list[NotionPage]:
        # Search returns collections; their database containers are resolved
        # through parent metadata. One database can contain several collections.
        return self._search(credentials=credentials, object_type="data_source")

    def _search(self, *, credentials: OAuthCredentials, object_type: str) -> list[NotionPage]:
        pages: list[NotionPage] = []
        cursor: str | None = None
        while True:
            payload: dict[str, object] = {"filter": {"property": "object", "value": object_type}, "page_size": 100}
            if cursor:
                payload["start_cursor"] = cursor
            data = self._request("POST", "/v1/search", credentials=credentials, json=payload)
            pages.extend(self._page(item) for item in data.get("results", [])
                         if isinstance(item, dict) and not item.get("archived") and not item.get("in_trash"))
            if not data.get("has_more"):
                return pages
            cursor = str(data.get("next_cursor"))

    def retrieve_page(self, *, credentials: OAuthCredentials, page_id: str) -> NotionPage:
        item = self._request("GET", f"/v1/pages/{page_id}", credentials=credentials)
        if item.get("archived") or item.get("in_trash"):
            raise SourceItemUnavailable("archived")
        return self._page(item)

    def retrieve_database(self, *, credentials: OAuthCredentials, database_id: str) -> NotionPage:
        item = self._request("GET", f"/v1/databases/{database_id}", credentials=credentials)
        if item.get("archived") or item.get("in_trash"):
            raise SourceItemUnavailable("archived")
        return self._page(item)

    def retrieve_data_source(self, *, credentials: OAuthCredentials, data_source_id: str) -> NotionPage:
        item = self._request("GET", f"/v1/data_sources/{data_source_id}", credentials=credentials)
        if item.get("archived") or item.get("in_trash"):
            raise SourceItemUnavailable("archived")
        return self._page(item)

    def data_source_pages(self, *, credentials: OAuthCredentials, data_source_id: str) -> list[NotionPage]:
        pages: list[NotionPage] = []
        cursor = None
        while True:
            payload: dict[str, object] = {"page_size": 100}
            if cursor:
                payload["start_cursor"] = cursor
            data = self._request("POST", f"/v1/data_sources/{data_source_id}/query", credentials=credentials, json=payload)
            pages.extend(self._page(item) for item in data.get("results", [])
                         if isinstance(item, dict) and not item.get("archived") and not item.get("in_trash"))
            if not data.get("has_more"):
                return pages
            cursor = str(data["next_cursor"])

    def block_parent(self, *, credentials: OAuthCredentials, block_id: str) -> tuple[str, str] | None:
        seen: set[str] = set()
        while block_id not in seen and len(seen) < 32:
            seen.add(block_id)
            item = self._request("GET", f"/v1/blocks/{block_id}", credentials=credentials)
            parent = item.get("parent") or {}
            kind = parent.get("type")
            value = parent.get(kind)
            if kind in {"page_id", "database_id", "data_source_id"} and value:
                return str(kind), notion_item_id(str(value))
            if kind != "block_id" or not value:
                return None
            block_id = str(value)
        return None

    def page_references(self, *, credentials: OAuthCredentials, page_id: str) -> list[dict[str, object]]:
        # Search is eventually consistent: unchanged parents must still expose
        # new child pages/databases that search has not indexed yet.
        return self.page_blocks(credentials=credentials, page_id=page_id)

    def page_blocks(self, *, credentials: OAuthCredentials, page_id: str) -> list[dict[str, object]]:
        return self._children_tree(credentials=credentials, block_id=page_id)

    def _children_tree(self, *, credentials: OAuthCredentials, block_id: str, depth: int = 0) -> list[dict[str, object]]:
        """Read a page's own block tree, including toggles and columns.

        Notion pages often contain their useful text below a container block.
        Reading only the first level makes those pages look empty and marks
        the whole sync as a partial failure even though the OAuth token works.
        The depth guard protects the worker from malformed or cyclic remote
        trees while keeping the request bounded.
        """
        if depth > 32:
            raise RuntimeError("notion_block_depth_limit")
        blocks: list[dict[str, object]] = []
        cursor: str | None = None
        while True:
            params = {"page_size": "100"}
            if cursor:
                params["start_cursor"] = cursor
            data = self._request("GET", f"/v1/blocks/{block_id}/children", credentials=credentials, params=params)
            for item in data.get("results", []):
                if not isinstance(item, dict):
                    continue
                if item.get("archived") or item.get("in_trash"):
                    continue
                blocks.append(item)
                if (item.get("has_children") is True and item.get("id")
                        and item.get("type") not in {"child_page", "child_database", "link_to_page"}):
                    blocks.extend(
                        self._children_tree(credentials=credentials, block_id=str(item["id"]), depth=depth + 1)
                    )
            if not data.get("has_more"):
                return blocks
            cursor = str(data.get("next_cursor"))

    def _request(self, method: str, path: str, *, credentials: OAuthCredentials, **kwargs: object) -> dict[str, object]:
        headers = {"Authorization": f"Bearer {credentials.access_token}", "Notion-Version": NOTION_API_VERSION}
        response = self.http.request(method, f"https://api.notion.com{path}", headers=headers, timeout=20, **kwargs)
        if response.status_code == 401:
            raise NotionRemoteUnauthorized()
        if response.status_code in {403, 404}:
            raise SourceItemUnavailable("restricted_resource" if response.status_code == 403 else "object_not_found")
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _page(item: dict[str, object]) -> NotionPage:
        properties = item.get("properties") or {}
        title = _rich_text(item.get("title")) or "Sem título"
        property_lines: list[str] = []
        if isinstance(properties, dict):
            for name, prop in properties.items():
                if isinstance(prop, dict) and prop.get("type") == "title":
                    title = _rich_text(prop.get("title")) or "Sem título"
                elif isinstance(prop, dict) and (value := _property_text(prop)):
                    property_lines.append(f"{name}: {value}")
        edited = item.get("last_edited_time")
        parent = item.get("parent") or {}
        parent_type = parent.get("type") if isinstance(parent, dict) else None
        parent_id = parent.get(parent_type) if isinstance(parent, dict) and parent_type else None
        return NotionPage(notion_item_id(str(item["id"])), title, str(item.get("url") or ""),
                          datetime.fromisoformat(str(edited)) if edited else None,
                          (notion_item_id(str(parent_id)),) if parent_type != "workspace" and parent_id else (),
                          parent_type, str(item.get("object") or "page"), "\n".join(property_lines),
                          tuple(notion_item_id(str(source["id"])) for source in item.get("data_sources", [])
                                if isinstance(source, dict) and source.get("id")))


class NotionConnectionService(OAuthConnectionServiceBase):
    provider = "notion"
    access_denied = NotionAccessDenied
    invalid = NotionOAuthInvalid

    def __init__(self, session: Session, cipher, client: NotionOAuthClient):
        super().__init__(session, cipher)
        self.client = client

    def disconnect(self, *, scope: OrganizationScope, user_id: UUID, source_id: UUID) -> DataSource:
        self.require_admin(scope=scope, user_id=user_id)
        source = self.session.scalar(select(DataSource).where(
            DataSource.id == source_id,
            DataSource.organization_id == scope.organization_id,
            DataSource.provider == "notion",
        ))
        if source is None:
            raise NotionAccessDenied("Notion source is invalid")
        source.encrypted_credentials = None
        source.account_email = None
        source.status = "disconnected"
        self.session.execute(update(OAuthConnectionState).where(
            OAuthConnectionState.source_id == source.id,
            OAuthConnectionState.consumed_at.is_(None),
        ).values(consumed_at=datetime.now(UTC)))
        self.session.add(AuditLog(organization_id=scope.organization_id, actor_user_id=user_id,
            action="data_source.disconnected", target_type="data_source", target_id=source.id))
        self.session.flush()
        return source

    def begin(self, *, scope: OrganizationScope, user_id: UUID, session_secret: str, source_id: UUID | None = None) -> str:
        self.require_admin(scope=scope, user_id=user_id)
        if source_id is not None:
            source = self.session.scalar(select(DataSource).where(
                DataSource.id == source_id,
                DataSource.organization_id == scope.organization_id,
                DataSource.provider == "notion",
            ))
            if source is None:
                raise NotionOAuthInvalid("Notion source is invalid")
        raw = self._new_state(scope=scope, user_id=user_id, session_secret=session_secret, source_id=source_id)
        return self.client.authorization_url(state=raw)

    def complete(self, *, raw_state: str, code: str, session_secret: str) -> DataSource:
        state = self._consume_state(raw_state=raw_state, session_secret=session_secret)
        credentials = self.client.exchange_code(code=code)
        account_email = self.client.account_email(credentials=credentials)
        source = self.session.scalar(select(DataSource).where(DataSource.id == state.source_id, DataSource.organization_id == state.organization_id, DataSource.provider == "notion")) if state.source_id else self.session.scalar(
            select(DataSource)
            .where(DataSource.organization_id == state.organization_id, DataSource.provider == "notion")
            .order_by(DataSource.created_at.desc(), DataSource.id.desc())
        )
        if state.source_id is not None and source is None:
            raise NotionOAuthInvalid("Notion source is invalid")
        if source is None:
            source = DataSource(organization_id=state.organization_id, provider="notion", encrypted_credentials=self.cipher.encrypt(credentials), status="connected", account_email=account_email, connected_by_user_id=state.user_id)
            self.session.add(source)
        else:
            source.encrypted_credentials = self.cipher.encrypt(credentials)
            source.status = "connected"
            source.account_email = account_email
            source.connected_by_user_id = state.user_id
        state.consumed_at = datetime.now(UTC)
        self.session.flush()
        self.session.add(AuditLog(organization_id=state.organization_id, actor_user_id=state.user_id, action="data_source.connected", target_type="data_source", target_id=source.id))
        self.session.flush()
        return source


class NotionDocumentProvider:
    key = "notion"

    def __init__(self, client: NotionOAuthClient, cipher):
        self.client = client
        self.cipher = cipher
        self._catalog: dict[str, NotionPage] | None = None
        self._projection_folders: list[RemoteFolder] = []

    def _load_catalog(self, credentials: OAuthCredentials) -> dict[str, NotionPage]:
        pages = {page.id: page for page in self.client.list_pages(credentials=credentials)}
        list_databases = getattr(self.client, "list_databases", None)
        if list_databases:
            pages.update({page.id: page for page in list_databases(credentials=credentials)})
        return self._with_ancestors(pages, credentials)

    def _with_ancestors(self, pages: dict[str, NotionPage], credentials: OAuthCredentials) -> dict[str, NotionPage]:
        # Search may omit parents. Retrieve their metadata, never their body,
        # so a selected subpage can retain a comprehensible path.
        pending = list(pages.values())
        attempted: set[str] = set(pages)
        while pending:
            page = pending.pop()
            if page.parent_type == "block_id" and page.parent_ids:
                try:
                    parent = self.client.block_parent(credentials=credentials, block_id=page.parent_ids[0])
                except SourceItemUnavailable:
                    parent = None
                page = replace(page, parent_ids=(parent[1],) if parent else (),
                               parent_type=parent[0] if parent else None)
                pages[page.id] = page
            for parent_id in page.parent_ids:
                if parent_id in attempted:
                    continue
                attempted.add(parent_id)
                method, argument = {
                    "database_id": ("retrieve_database", "database_id"),
                    "data_source_id": ("retrieve_data_source", "data_source_id"),
                }.get(page.parent_type, ("retrieve_page", "page_id"))
                retrieve = getattr(self.client, method, None)
                if retrieve is None:
                    continue
                try:
                    ancestor = retrieve(credentials=credentials, **{argument: parent_id})
                except SourceItemUnavailable:
                    continue
                pages[ancestor.id] = ancestor
                pending.append(ancestor)
        return pages

    def folders(self, *, encrypted_credentials: str | None) -> list[RemoteFolder]:
        pages = self._load_catalog(self.cipher.decrypt(encrypted_credentials or ""))
        return [RemoteFolder(page.id, page.title, page.parent_ids, kind=page.object_type) for page in pages.values()]

    def folders_for_selections(self, *, encrypted_credentials, selections) -> list[RemoteFolder]:
        if self._catalog is None:
            self.discover(encrypted_credentials=encrypted_credentials, selections=selections)
        return self._projection_folders

    @staticmethod
    def _selected(pages: dict[str, NotionPage], selections) -> set[str]:
        if any(selection.kind == "all_accessible" for selection in selections):
            return set(pages)
        selected = {notion_item_id(selection.external_folder_id) for selection in selections if selection.kind == "folder"}
        while added := {page.id for page in pages.values() if set(page.parent_ids) & selected} - selected:
            selected.update(added)
        return selected & set(pages)

    def discover(
        self,
        *,
        encrypted_credentials: str | None,
        selections,
        known_documents: dict[str, tuple[datetime | None, str]] | None = None,
        force_file_ids: set[str] | None = None,
        force_full: bool = False,
    ) -> DiscoveryResult:
        from app.ingestion.service import DiscoveredDocument

        credentials = self.cipher.decrypt(encrypted_credentials or "")
        pages = self._load_catalog(credentials)
        known_documents = known_documents or {}
        known_ids = set(known_documents)
        # Absence from search does not prove a deletion. Confirm known and
        # explicitly selected pages directly before reconciling removals.
        retrieve = getattr(self.client, "retrieve_page", None)
        requested = {notion_item_id(s.external_folder_id) for s in selections if s.kind == "folder"}
        if retrieve:
            for page_id in sorted((known_ids | requested) - set(pages)):
                try:
                    pages[page_id] = retrieve(credentials=credentials, page_id=page_id)
                except SourceItemUnavailable:
                    if page_id in requested:
                        try:
                            pages[page_id] = self.client.retrieve_database(credentials=credentials, database_id=page_id)
                        except SourceItemUnavailable:
                            try:
                                pages[page_id] = self.client.retrieve_data_source(credentials=credentials, data_source_id=page_id)
                            except SourceItemUnavailable:
                                pass
        pages = self._with_ancestors(pages, credentials)
        selected_ids = self._selected(pages, selections)
        effective_known = {} if force_full else known_documents
        outcomes: dict[str, DiscoveredDocument | None] = {}
        processed: set[str] = set()

        def read_page(page: NotionPage):
            known = effective_known.get(page.id)
            unchanged = bool(known and known[1] == "indexed" and page.id not in (force_file_ids or set())
                             and page.last_edited_time is not None and known[0] == page.last_edited_time)
            references = getattr(self.client, "page_references", None)
            try:
                blocks = (references(credentials=credentials, page_id=page.id) if unchanged and references
                          else [] if unchanged else self.client.page_blocks(credentials=credentials, page_id=page.id))
            except SourceItemUnavailable:
                return page, [], None, False
            text = "" if unchanged else "\n\n".join(value for value in (
                page.properties_text, _blocks_to_text(blocks),
            ) if value)
            document = DiscoveredDocument(page.id, page.title, "text/markdown", page.url,
                                          modified_at=page.last_edited_time, text=text) if text.strip() else None
            return page, blocks, document, unchanged

        while pending := sorted(selected_ids - processed):
            database_ids = [id for id in pending if pages[id].object_type in {"database", "data_source"}]
            for database_id in database_ids:
                processed.add(database_id)
                if pages[database_id].object_type == "database":
                    for data_source_id in pages[database_id].data_source_ids:
                        if data_source_id not in pages:
                            try:
                                pages[data_source_id] = self.client.retrieve_data_source(
                                    credentials=credentials, data_source_id=data_source_id)
                            except SourceItemUnavailable:
                                continue
                    continue
                try:
                    rows = self.client.data_source_pages(credentials=credentials, data_source_id=database_id)
                except SourceItemUnavailable:
                    continue
                for row in rows:
                    pages[row.id] = replace(row, parent_ids=(database_id,), parent_type="data_source_id")
            selected_ids = self._selected(pages, selections)
            batch = [pages[id] for id in sorted(selected_ids - processed) if pages[id].object_type == "page"]
            with ThreadPoolExecutor(max_workers=min(MAX_PAGE_WORKERS, len(batch) or 1)) as executor:
                results = list(executor.map(read_page, batch))
            for page, blocks, document, unchanged in results:
                processed.add(page.id)
                if not unchanged:
                    outcomes[page.id] = document
                for block in blocks:
                    kind, child_id = block.get("type"), block.get("id")
                    if kind not in {"child_page", "child_database"} or not child_id:
                        continue
                    child_id = notion_item_id(str(child_id))
                    if child_id not in pages:
                        method = self.client.retrieve_database if kind == "child_database" else self.client.retrieve_page
                        try:
                            child = method(credentials=credentials, **{
                                "database_id" if kind == "child_database" else "page_id": child_id})
                        except SourceItemUnavailable:
                            continue
                    else:
                        child = pages[child_id]
                    if child.parent_type == "block_id" and child.parent_ids:
                        try:
                            parent = self.client.block_parent(credentials=credentials, block_id=child.parent_ids[0])
                        except SourceItemUnavailable:
                            continue
                        child = replace(child, parent_ids=(parent[1],) if parent else ())
                    if child.parent_ids and child.parent_ids != (page.id,):
                        # A child-page block copied through a synced block is
                        # a reference to its actual parent, not a new subtree.
                        continue
                    # A child block nested in a toggle still belongs to this page.
                    pages[child_id] = replace(child, parent_ids=(page.id,), parent_type="page_id")
            selected_ids = self._selected(pages, selections)

        # Only ancestors of selected objects are projected, not every search
        # result. A page is a grouping node only if it contains selected children.
        container_ids = {id for id in selected_ids if pages[id].object_type in {"database", "data_source"}}
        pending = list(selected_ids)
        visited: set[str] = set()
        while pending:
            page_id = pending.pop()
            if page_id in visited:
                continue
            visited.add(page_id)
            for parent_id in pages[page_id].parent_ids:
                if parent_id in pages:
                    container_ids.add(parent_id)
                    pending.append(parent_id)
        self._projection_folders = [RemoteFolder(
            NOTION_CONTAINER_PREFIX + id, pages[id].title,
            tuple(NOTION_CONTAINER_PREFIX + parent for parent in pages[id].parent_ids
                  if parent in container_ids and not self._cyclic_parent(id, parent, pages)),
            kind=pages[id].object_type,
        ) for id in sorted(container_ids)]

        def metadata(page: NotionPage) -> DiscoveredDocument:
            parents = (page.id,) if page.id in container_ids else page.parent_ids
            return DiscoveredDocument(
                page.id, f"Conteúdo de {page.title}" if page.id in container_ids else page.title,
                "text/markdown", page.url, modified_at=page.last_edited_time,
                parent_ids=tuple(NOTION_CONTAINER_PREFIX + id for id in parents if id in container_ids),
            )

        empty_ids = {id for id, document in outcomes.items() if document is None}
        catalog_ids = {id for id in selected_ids if pages[id].object_type == "page"
                       and id not in empty_ids and (outcomes.get(id) is not None or
                       (id in effective_known and effective_known[id][1] == "indexed"))}
        catalog_documents = [metadata(pages[id]) for id in sorted(catalog_ids)]
        documents = [replace(metadata(pages[id]), text=document.text)
                     for id, document in sorted(outcomes.items()) if document is not None]
        self._catalog = pages
        return DiscoveryResult(
            documents=documents,
            removed_file_ids=tuple(sorted((known_ids - selected_ids) | empty_ids)),
            full_snapshot=not bool(known_ids) or force_full,
            catalog_documents=catalog_documents,
        )

    @staticmethod
    def _cyclic_parent(page_id: str, parent_id: str, pages: dict[str, NotionPage]) -> bool:
        pending, seen = [parent_id], set()
        while pending:
            current = pending.pop()
            if current == page_id:
                return True
            if current not in seen and current in pages:
                seen.add(current)
                pending.extend(pages[current].parent_ids)
        return False


def _blocks_to_text(blocks: list[dict[str, object]]) -> str:
    lines: list[str] = []
    for block in blocks:
        kind = str(block.get("type") or "")
        payload = block.get(kind) or {}
        if not isinstance(payload, dict) or kind in {"child_page", "child_database"}:
            continue
        text = _rich_text(payload.get("rich_text") or payload.get("caption"))
        if kind == "table_row":
            text = " | ".join(_rich_text(cell) for cell in payload.get("cells", []))
        elif kind == "equation":
            text = str(payload.get("expression") or "")
        elif kind == "link_to_page":
            target = payload.get(str(payload.get("type")))
            if target:
                text = f"Referência: https://www.notion.so/{str(target).replace('-', '')}"
        elif kind in {"bookmark", "link_preview", "embed"}:
            url = payload.get("url")
            if url:
                text = f"{text} ({url})" if text else f"Referência: {url}"
        elif kind in {"file", "pdf", "image", "audio", "video"}:
            # Signed attachment URLs expire. Keep the label/caption; do not
            # embed ephemeral URLs or treat attachment bytes as page text.
            name = payload.get("name")
            text = " · ".join(str(value) for value in (name, text) if value)
            text = f"Anexo: {text}" if text else ""
        if text:
            lines.append(text)
        rich_text = payload.get("rich_text") or payload.get("caption") or []
        for item in rich_text if isinstance(rich_text, list) else []:
            if not isinstance(item, dict):
                continue
            href = item.get("href")
            if isinstance(href, str) and href.startswith(("https://", "http://")) and href != item.get("plain_text"):
                lines.append(f"Referência: {href}")
    return "\n\n".join(lines)
