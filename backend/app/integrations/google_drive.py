"""Google Drive OAuth port; credentials never leave this module as plaintext."""

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import quote, urlencode
from uuid import UUID

import httpx
from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.integrations.credentials import OAuthCredentials
from app.integrations.errors import SourceItemUnavailable, SourceRemoteUnauthorized
from app.integrations.http import RemoteHttp, RemoteThrottled, parse_retry_after
from app.integrations.keyring import build_fernet, rotate_token
from app.integrations.models import DataSource
from app.integrations.oauth_base import OAuthConnectionServiceBase

GOOGLE_DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"


class GoogleOAuthUnavailable(RuntimeError):
    pass


class GoogleOAuthInvalid(ValueError):
    pass


class GoogleAccessDenied(PermissionError):
    pass


class GoogleRemoteUnauthorized(SourceRemoteUnauthorized):
    pass


class GoogleRefreshTokenInvalid(GoogleRemoteUnauthorized):
    """The stored Google refresh token was revoked or expired."""


class GoogleCursorInvalid(GoogleOAuthInvalid):
    """The Drive Changes page token expired and needs a fresh snapshot."""


@dataclass(frozen=True)
class GoogleChangesPage:
    changes: list[dict[str, object]]
    new_start_page_token: str


logger = logging.getLogger("document_intelligence.integration")


GoogleCredentials = OAuthCredentials

@dataclass(frozen=True)
class RemoteFolder:
    id: str
    name: str
    parent_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RemoteFile:
    id: str
    name: str
    mime_type: str
    source_url: str
    modified_at: datetime | None
    parent_ids: tuple[str, ...] = ()
    size: int | None = None  # bytes; absent for Google-native files


class GoogleDrivePort(Protocol):
    def authorization_url(self, *, state: str, scope: str) -> str: ...
    def exchange_code(self, *, code: str) -> GoogleCredentials: ...
    def account_email(self, *, credentials: GoogleCredentials) -> str | None: ...
    def list_folders(self, *, credentials: GoogleCredentials) -> list[RemoteFolder]: ...


class GoogleItemUnavailable(SourceItemUnavailable):
    pass


class GoogleItemTooLarge(GoogleItemUnavailable):
    """Google refused to export the file because it exceeds its own export cap."""


QUOTA_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded", "sharingRateLimitExceeded"})
DAILY_QUOTA_REASONS = frozenset({"dailyLimitExceeded"})
from app.ingestion.extraction.mime import GOOGLE_EXPORT_MIME

ITEM_FORBIDDEN_REASONS = frozenset(
    {"insufficientFilePermissions", "appNotAuthorizedToFile", "cannotDownloadFile", "fileNotDownloadable", "exportSizeLimitExceeded"}
)


def google_error_reason(response: httpx.Response) -> str | None:
    try:
        error = response.json()["error"]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(error, dict):
        return None
    for entry in error.get("errors") or []:
        if isinstance(entry, dict) and isinstance(entry.get("reason"), str):
            return entry["reason"]
    for entry in error.get("details") or []:
        if isinstance(entry, dict) and isinstance(entry.get("reason"), str):
            return entry["reason"]
    return None


def _google_retryable(response: httpx.Response) -> bool:
    return response.status_code == 403 and google_error_reason(response) in QUOTA_REASONS


def raise_for_google(response: httpx.Response) -> None:
    """Map a Drive response to the domain errors; the ONLY place that reads 401/403."""
    if response.status_code == 401:
        raise GoogleRemoteUnauthorized()
    if response.status_code == 403:
        reason = google_error_reason(response)
        if reason in DAILY_QUOTA_REASONS or reason in QUOTA_REASONS:
            raise RemoteThrottled(parse_retry_after(response.headers.get("Retry-After")), reason=reason)
        if reason == "exportSizeLimitExceeded":
            raise GoogleItemTooLarge(reason)
        if reason in ITEM_FORBIDDEN_REASONS:
            raise GoogleItemUnavailable(reason)
        raise GoogleRemoteUnauthorized()
    response.raise_for_status()


class GoogleDriveOAuthClient:
    def __init__(
        self, *, client_id: str | None, client_secret: str | None, redirect_uri: str | None, http: RemoteHttp | None = None
    ):
        self.http = http or RemoteHttp(is_retryable=_google_retryable)
        self.client_id, self.client_secret, self.redirect_uri = (
            client_id,
            client_secret,
            redirect_uri,
        )

    def _configured(self) -> None:
        if not self.client_id or not self.client_secret or not self.redirect_uri:
            raise GoogleOAuthUnavailable("Google OAuth is not configured")

    def authorization_url(self, *, state: str, scope: str) -> str:
        self._configured()
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": scope,
                "state": state,
                "access_type": "offline",
                "prompt": "consent",
            }
        )

    def exchange_code(self, *, code: str) -> GoogleCredentials:
        self._configured()
        response = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=10,
        )
        if response.status_code in {400, 401, 403}:
            raise GoogleOAuthInvalid("Google authorization failed")
        raise_for_google(response)
        data = response.json()
        return GoogleCredentials(data["access_token"], data.get("refresh_token"), None)

    def refresh_access_token(self, *, refresh_token: str) -> GoogleCredentials:
        self._configured()
        response = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=10,
        )
        if response.status_code == 400:
            try:
                error = response.json().get("error")
            except (ValueError, TypeError):
                error = None
            if error == "invalid_grant":
                raise GoogleRefreshTokenInvalid("Google refresh token is invalid")
        response.raise_for_status()
        data = response.json()
        return GoogleCredentials(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token") or refresh_token,
            expires_at=datetime.now(UTC) + timedelta(seconds=int(data["expires_in"])),
        )

    def account_email(self, *, credentials: GoogleCredentials) -> str | None:
        response = self.http.request("GET",
            "https://www.googleapis.com/drive/v3/about",
            params={"fields": "user(emailAddress)"},
            headers={"Authorization": f"Bearer {credentials.access_token}"},
            timeout=10,
        )
        raise_for_google(response)
        email = response.json().get("user", {}).get("emailAddress")
        return str(email).strip().lower() if isinstance(email, str) and email.strip() else None

    def list_folders(self, *, credentials: GoogleCredentials) -> list[RemoteFolder]:
        folders: list[RemoteFolder] = []
        page_token: str | None = None
        while True:
            response = self._list_response(
                credentials=credentials,
                query="mimeType = 'application/vnd.google-apps.folder' and trashed = false",
                fields="nextPageToken,files(id,name,parents)",
                page_token=page_token,
            )
            data = response.json()
            folders.extend(
                RemoteFolder(item["id"], item["name"], tuple(item.get("parents", [])))
                for item in data.get("files", [])
            )
            page_token = data.get("nextPageToken")
            if page_token is None:
                return folders

    def start_page_token(self, *, credentials: GoogleCredentials) -> str:
        response = self.http.request("GET",
            "https://www.googleapis.com/drive/v3/changes/startPageToken",
            params={"supportsAllDrives": "true"},
            headers={"Authorization": f"Bearer {credentials.access_token}"},
            timeout=20,
        )
        raise_for_google(response)
        token = response.json().get("startPageToken")
        if not isinstance(token, str) or not token:
            raise GoogleOAuthInvalid("Google Drive change token is invalid")
        return token

    def get_file(self, *, credentials: GoogleCredentials, file_id: str) -> RemoteFile | None:
        response = self.http.request("GET",
            f"https://www.googleapis.com/drive/v3/files/{quote(file_id, safe='')}",
            params={"fields": "id,name,mimeType,modifiedTime,webViewLink,parents,size,trashed", "supportsAllDrives": "true"},
            headers={"Authorization": f"Bearer {credentials.access_token}"},
            timeout=20,
        )
        if response.status_code == 404:
            return None
        raise_for_google(response)
        item = response.json()
        if item.get("trashed") or not item.get("id") or not item.get("mimeType"):
            return None
        return self._remote_file(item)

    def changes(self, *, credentials: GoogleCredentials, page_token: str) -> GoogleChangesPage:
        changes: list[dict[str, object]] = []
        while True:
            response = self.http.request("GET",
                "https://www.googleapis.com/drive/v3/changes",
                params={
                    "pageToken": page_token,
                    "pageSize": 1000,
                    "spaces": "drive",
                    "includeItemsFromAllDrives": "true",
                    "supportsAllDrives": "true",
                    "fields": "nextPageToken,newStartPageToken,changes(fileId,removed,file(id,name,mimeType,modifiedTime,webViewLink,parents,size,trashed))",
                },
                headers={"Authorization": f"Bearer {credentials.access_token}"},
                timeout=20,
            )
            if response.status_code in {400, 410}:
                raise GoogleCursorInvalid("Google Drive change cursor expired")
            raise_for_google(response)
            payload = response.json()
            page_changes = payload.get("changes", [])
            if isinstance(page_changes, list):
                changes.extend(item for item in page_changes if isinstance(item, dict))
            next_token = payload.get("nextPageToken")
            if isinstance(next_token, str):
                page_token = next_token
                continue
            new_token = payload.get("newStartPageToken")
            if isinstance(new_token, str) and new_token:
                return GoogleChangesPage(changes, new_token)
            raise GoogleOAuthInvalid("Google Drive change response is incomplete")

    def list_folder_files(
        self, *, credentials: GoogleCredentials, root_folder_id: str
    ) -> list[RemoteFile]:
        """List files in a selected folder and all descendants without retaining bytes."""
        folders_to_visit = [root_folder_id]
        visited_folders: set[str] = set()
        files: list[RemoteFile] = []
        while folders_to_visit:
            folder_id = folders_to_visit.pop()
            if folder_id in visited_folders:
                continue
            visited_folders.add(folder_id)
            page_token: str | None = None
            while True:
                response = self._list_response(
                    credentials=credentials,
                    query=f"'{folder_id}' in parents and trashed = false",
                    fields="nextPageToken,files(id,name,mimeType,modifiedTime,webViewLink,parents,size)",
                    page_token=page_token,
                )
                data = response.json()
                for item in data.get("files", []):
                    if item["mimeType"] == "application/vnd.google-apps.folder":
                        folders_to_visit.append(item["id"])
                        continue
                    modified = item.get("modifiedTime")
                    files.append(
                        RemoteFile(
                            id=item["id"],
                            name=item["name"],
                            mime_type=item["mimeType"],
                            source_url=item.get("webViewLink")
                            or f"https://drive.google.com/open?id={item['id']}",
                            modified_at=datetime.fromisoformat(modified) if modified else None,
                            parent_ids=tuple(item.get("parents", [])),
                        )
                    )
                page_token = data.get("nextPageToken")
                if page_token is None:
                    break
        return files

    def list_root_files(self, *, credentials: GoogleCredentials) -> list[RemoteFile]:
        return self._list_nonfolder_files(
            credentials=credentials,
            query="'root' in parents and trashed = false",
        )

    def list_all_files(self, *, credentials: GoogleCredentials) -> list[RemoteFile]:
        return self._list_nonfolder_files(credentials=credentials, query="trashed = false")

    def _list_nonfolder_files(
        self, *, credentials: GoogleCredentials, query: str
    ) -> list[RemoteFile]:
        files: list[RemoteFile] = []
        page_token: str | None = None
        while True:
            response = self._list_response(
                credentials=credentials,
                query=f"{query} and mimeType != 'application/vnd.google-apps.folder'",
                fields="nextPageToken,files(id,name,mimeType,modifiedTime,webViewLink,parents,size)",
                page_token=page_token,
            )
            data = response.json()
            files.extend(self._remote_file(item) for item in data.get("files", []))
            page_token = data.get("nextPageToken")
            if page_token is None:
                return files

    @staticmethod
    def _remote_file(item: dict[str, object]) -> RemoteFile:
        modified = item.get("modifiedTime")
        return RemoteFile(
            id=str(item["id"]),
            name=str(item["name"]),
            mime_type=str(item["mimeType"]),
            source_url=str(
                item.get("webViewLink") or f"https://drive.google.com/open?id={item['id']}"
            ),
            modified_at=datetime.fromisoformat(str(modified)) if modified else None,
            parent_ids=tuple(str(parent) for parent in item.get("parents", [])),
            size=int(item["size"]) if str(item.get("size") or "").isdigit() else None,
        )

    def _list_response(
        self, *, credentials: GoogleCredentials, query: str, fields: str, page_token: str | None
    ) -> httpx.Response:
        response = self.http.request("GET",
            "https://www.googleapis.com/drive/v3/files",
            params={
                "q": query,
                "fields": fields,
                "pageSize": 1000,
                "pageToken": page_token,
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            },
            headers={"Authorization": f"Bearer {credentials.access_token}"},
            timeout=20,
        )
        raise_for_google(response)
        return response

    def read_file(self, *, credentials: GoogleCredentials, remote_file: RemoteFile) -> bytes:
        export_mime = GOOGLE_EXPORT_MIME.get(remote_file.mime_type)
        if export_mime:
            url = f"https://www.googleapis.com/drive/v3/files/{remote_file.id}/export"
            response = self.http.request("GET",
                url,
                params={"mimeType": export_mime},
                headers={"Authorization": f"Bearer {credentials.access_token}"},
                timeout=30,
            )
        else:
            response = self.http.request("GET",
                f"https://www.googleapis.com/drive/v3/files/{remote_file.id}",
                params={"alt": "media"},
                headers={"Authorization": f"Bearer {credentials.access_token}"},
                timeout=30,
            )
        raise_for_google(response)
        return response.content


class CredentialCipher:
    def __init__(self, key: str | None, *, fallback_keys=()):
        self.key = key
        self._keys = [key, *fallback_keys]

    def encrypt(self, credentials: GoogleCredentials) -> str:
        payload = "|".join(
            [
                credentials.access_token,
                credentials.refresh_token or "",
                credentials.expires_at.isoformat() if credentials.expires_at else "",
            ]
        )
        return self._fernet().encrypt(payload.encode()).decode()

    def decrypt(self, value: str) -> GoogleCredentials:
        try:
            access, refresh, expires = (
                self._fernet().decrypt(value.encode()).decode().split("|", 2)
            )
        except (InvalidToken, ValueError) as error:
            raise GoogleOAuthInvalid("credential unavailable") from error
        return GoogleCredentials(
            access, refresh or None, datetime.fromisoformat(expires) if expires else None
        )

    def encrypt_cursor(self, value: str) -> str:
        return self._fernet().encrypt(value.encode()).decode()

    def decrypt_cursor(self, value: str) -> str:
        try:
            return self._fernet().decrypt(value.encode()).decode()
        except (InvalidToken, ValueError) as error:
            raise GoogleCursorInvalid("change cursor unavailable") from error

    def _fernet(self):
        try:
            fernet = build_fernet(self._keys)
        except (ValueError, TypeError) as error:
            raise GoogleOAuthUnavailable("token encryption is not configured") from error
        if fernet is None:
            raise GoogleOAuthUnavailable("token encryption is not configured")
        return fernet

    def rotate(self, value: str) -> str:
        return rotate_token(self._fernet(), value)


class GoogleConnectionService(OAuthConnectionServiceBase):
    provider = "google_drive"
    access_denied = GoogleAccessDenied
    invalid = GoogleOAuthInvalid

    def __init__(self, session: Session, cipher: CredentialCipher):
        super().__init__(session, cipher)

    def begin(
        self,
        *,
        scope: OrganizationScope,
        user_id: UUID,
        session_secret: str,
        port: GoogleDrivePort,
        reauth_source_id: UUID | None = None,
    ) -> str:
        self.require_admin(scope=scope, user_id=user_id)
        if (
            reauth_source_id is not None
            and self.session.scalar(
                select(DataSource).where(
                    DataSource.id == reauth_source_id,
                    DataSource.organization_id == scope.organization_id,
                    DataSource.provider == "google_drive",
                )
            )
            is None
        ):
            raise GoogleAccessDenied("source access denied")
        raw = self._new_state(scope=scope, user_id=user_id, session_secret=session_secret, source_id=reauth_source_id)
        url = port.authorization_url(state=raw, scope=GOOGLE_DRIVE_READONLY_SCOPE)
        logger.info(
            "google connection started",
            extra={
                "event": "google_connection",
                "provider": "google_drive",
                "action": "start",
                "result": "redirected",
                "elapsed_ms": 0.0,
            },
        )
        return url

    def complete(
        self, *, raw_state: str, code: str, session_secret: str, port: GoogleDrivePort
    ) -> DataSource:
        state = self._consume_state(raw_state=raw_state, session_secret=session_secret)
        started = time.perf_counter()
        try:
            credentials = port.exchange_code(code=code)
            account_email = port.account_email(credentials=credentials)
        except Exception:
            logger.warning(
                "google connection failed",
                extra={
                    "event": "google_connection",
                    "provider": "google_drive",
                    "action": "complete",
                    "result": "failed",
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            raise
        source = (
            self.session.scalar(
                select(DataSource).where(
                    DataSource.id == state.source_id,
                    DataSource.organization_id == state.organization_id,
                )
            )
            if state.source_id
            else None
        )
        if source is None:
            source = DataSource(
                organization_id=state.organization_id,
                provider="google_drive",
                encrypted_credentials=self.cipher.encrypt(credentials),
                status="connected",
                account_email=account_email,
                connected_by_user_id=state.user_id,
            )
            self.session.add(source)
        else:
            source.encrypted_credentials = self.cipher.encrypt(credentials)
            source.status = "connected"
            source.account_email = account_email
            source.connected_by_user_id = state.user_id
        state.consumed_at = datetime.now(UTC)
        self.session.flush()
        logger.info(
            "google connection complete",
            extra={
                "event": "google_connection",
                "provider": "google_drive",
                "action": "complete",
                "result": "connected",
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return source

    def sources(self, *, scope: OrganizationScope, user_id: UUID) -> list[DataSource]:
        self.require_admin(scope=scope, user_id=user_id)
        return list(
            self.session.scalars(
                select(DataSource)
                .where(DataSource.organization_id == scope.organization_id)
                .order_by(DataSource.created_at, DataSource.id)
            )
        )


    def folders(
        self, *, scope: OrganizationScope, user_id: UUID, source_id: UUID, port: GoogleDrivePort
    ) -> list[RemoteFolder]:
        self.require_admin(scope=scope, user_id=user_id)
        source = self.session.scalar(
            select(DataSource).where(
                DataSource.id == source_id,
                DataSource.organization_id == scope.organization_id,
                DataSource.status == "connected",
            )
        )
        if source is None:
            raise GoogleAccessDenied("source access denied")
        try:
            return port.list_folders(credentials=self.cipher.decrypt(source.encrypted_credentials))
        except GoogleRemoteUnauthorized:
            source.status = "reauth_required"
            self.session.flush()
            logger.warning(
                "google source requires reauthentication",
                extra={
                    "event": "google_connection",
                    "provider": "google_drive",
                    "action": "list_folders",
                    "result": "reauth_required",
                    "elapsed_ms": 0.0,
                },
            )
            raise GoogleOAuthInvalid("source requires reauthentication")
