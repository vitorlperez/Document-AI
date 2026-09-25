"""Notion OAuth and API adapter."""

import base64
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_usage.models import AuditLog
from app.core.scoping import OrganizationScope
from app.identity.auth import hash_secret
from app.identity.models import UserSession
from app.integrations.google_drive import GoogleCredentials, GoogleRemoteUnauthorized, RemoteFolder
from app.integrations.models import DataSource, OAuthConnectionState
from app.organizations.models import Membership, MembershipRole

NOTION_READ_SCOPE = ""
MAX_PAGE_WORKERS = 2
NOTION_REQUEST_INTERVAL_SECONDS = 0.35


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


class NotionOAuthClient:
    def __init__(self, *, client_id: str | None, client_secret: str | None, redirect_uri: str | None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self._request_lock = threading.Lock()
        self._next_request_at = 0.0

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

    def exchange_code(self, *, code: str) -> GoogleCredentials:
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
        return GoogleCredentials(access_token=str(data["access_token"]), refresh_token=None, expires_at=None)

    def account_email(self, *, credentials: GoogleCredentials) -> str | None:
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

    def list_pages(self, *, credentials: GoogleCredentials) -> list[NotionPage]:
        pages: list[NotionPage] = []
        cursor: str | None = None
        while True:
            payload: dict[str, object] = {"filter": {"property": "object", "value": "page"}, "page_size": 100}
            if cursor:
                payload["start_cursor"] = cursor
            data = self._request("POST", "/v1/search", credentials=credentials, json=payload)
            pages.extend(self._page(item) for item in data.get("results", []) if isinstance(item, dict))
            if not data.get("has_more"):
                return pages
            cursor = str(data.get("next_cursor"))

    def page_blocks(self, *, credentials: GoogleCredentials, page_id: str) -> list[dict[str, object]]:
        return self._children_tree(credentials=credentials, block_id=page_id)

    def _children_tree(self, *, credentials: GoogleCredentials, block_id: str, depth: int = 0) -> list[dict[str, object]]:
        """Read a page's block tree, including toggles, columns and child pages.

        Notion pages often contain their useful text below a container block.
        Reading only the first level makes those pages look empty and marks
        the whole sync as a partial failure even though the OAuth token works.
        The depth guard protects the worker from malformed or cyclic remote
        trees while keeping the request bounded.
        """
        if depth > 12:
            return []
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
                blocks.append(item)
                if item.get("has_children") is True and item.get("id"):
                    blocks.extend(
                        self._children_tree(credentials=credentials, block_id=str(item["id"]), depth=depth + 1)
                    )
            if not data.get("has_more"):
                return blocks
            cursor = str(data.get("next_cursor"))

    def _request(self, method: str, path: str, *, credentials: GoogleCredentials, **kwargs: object) -> dict[str, object]:
        headers = {"Authorization": f"Bearer {credentials.access_token}", "Notion-Version": "2022-06-28"}
        # Notion's requests are shared by concurrent page readers. Space their
        # starts to avoid turning a faster sync into a burst of 429 responses.
        with self._request_lock:
            now = time.monotonic()
            delay = max(0.0, self._next_request_at - now)
            if delay:
                time.sleep(delay)
            self._next_request_at = time.monotonic() + NOTION_REQUEST_INTERVAL_SECONDS
        response = httpx.request(method, f"https://api.notion.com{path}", headers=headers, timeout=20, **kwargs)
        if response.status_code in {401, 403}:
            raise GoogleRemoteUnauthorized()
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _page(item: dict[str, object]) -> NotionPage:
        properties = item.get("properties") or {}
        title = "Untitled"
        if isinstance(properties, dict):
            for prop in properties.values():
                if isinstance(prop, dict) and prop.get("type") == "title":
                    values = prop.get("title") or []
                    if values and isinstance(values[0], dict):
                        title = str(values[0].get("plain_text") or "Untitled")
                    break
        edited = item.get("last_edited_time")
        return NotionPage(str(item["id"]), title, str(item.get("url") or ""), datetime.fromisoformat(str(edited)) if edited else None)


class NotionConnectionService:
    def __init__(self, session: Session, cipher, client: NotionOAuthClient):
        self.session, self.cipher, self.client = session, cipher, client

    def require_admin(self, *, scope: OrganizationScope, user_id: UUID) -> None:
        member = self.session.scalar(select(Membership).where(Membership.organization_id == scope.organization_id, Membership.user_id == user_id, Membership.is_active.is_(True), Membership.role.in_([MembershipRole.OWNER, MembershipRole.ADMIN])))
        if member is None:
            raise NotionAccessDenied("integration access denied")

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
        raw = secrets.token_urlsafe(32)
        self.session.add(OAuthConnectionState(organization_id=scope.organization_id, user_id=user_id, source_id=source_id, session_hash=hash_secret(session_secret), state_hash=hash_secret(raw), expires_at=datetime.now(UTC) + timedelta(minutes=10)))
        self.session.flush()
        return self.client.authorization_url(state=raw)

    def complete(self, *, raw_state: str, code: str, session_secret: str) -> DataSource:
        state = self.session.scalar(select(OAuthConnectionState).where(OAuthConnectionState.state_hash == hash_secret(raw_state), OAuthConnectionState.consumed_at.is_(None), OAuthConnectionState.expires_at > datetime.now(UTC)))
        active_session = self.session.scalar(select(UserSession).where(UserSession.secret_hash == hash_secret(session_secret), UserSession.user_id == state.user_id if state else False, UserSession.revoked_at.is_(None), UserSession.expires_at > datetime.now(UTC))) if state else None
        if state is None or state.session_hash != hash_secret(session_secret) or active_session is None:
            raise NotionOAuthInvalid("OAuth state is invalid")
        self.require_admin(scope=OrganizationScope(state.organization_id), user_id=state.user_id)
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

    def folders(self, *, encrypted_credentials: str | None) -> list[RemoteFolder]:
        pages = self.client.list_pages(credentials=self.cipher.decrypt(encrypted_credentials or ""))
        return [RemoteFolder(page.id, page.title) for page in pages]

    def discover(self, *, encrypted_credentials: str | None, selections) -> list:
        credentials = self.cipher.decrypt(encrypted_credentials or "")
        pages = {page.id: page for page in self.client.list_pages(credentials=credentials)}
        selected_ids = (
            set(pages)
            if any(selection.kind == "all_accessible" for selection in selections)
            else {selection.external_folder_id for selection in selections if selection.kind == "folder"}
        )
        from app.ingestion.service import DiscoveredDocument
        selected_pages = [pages[page_id] for page_id in sorted(selected_ids) if page_id in pages]

        def read_page(page: NotionPage) -> DiscoveredDocument | None:
            text = _blocks_to_text(self.client.page_blocks(credentials=credentials, page_id=page.id))
            # Notion search also returns empty metadata pages (for example a
            # person/profile page). They are valid remote objects, but there
            # is no content to embed or cite. Skipping them keeps the sync
            # ready while still indexing every page with actual blocks.
            if not text.strip():
                return None
            return DiscoveredDocument(
                external_file_id=page.id,
                name=page.title,
                mime_type="text/markdown",
                source_url=page.url,
                modified_at=page.last_edited_time,
                text=text,
            )

        with ThreadPoolExecutor(max_workers=min(MAX_PAGE_WORKERS, len(selected_pages) or 1)) as executor:
            return [document for document in executor.map(read_page, selected_pages) if document is not None]


def _blocks_to_text(blocks: list[dict[str, object]]) -> str:
    lines: list[str] = []
    for block in blocks:
        kind = str(block.get("type") or "")
        payload = block.get(kind) or {}
        if not isinstance(payload, dict):
            continue
        rich_text = payload.get("rich_text") or payload.get("title") or []
        text = "".join(str(item.get("plain_text", "")) for item in rich_text if isinstance(item, dict))
        if text:
            lines.append(text)
    return "\n\n".join(lines)
