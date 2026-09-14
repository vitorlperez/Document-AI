"""Google Drive OAuth port; credentials never leave this module as plaintext."""

import logging
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlencode
from uuid import UUID

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.audit_usage.models import AuditLog
from app.core.scoping import OrganizationScope
from app.identity.auth import hash_secret
from app.identity.models import UserSession
from app.integrations.models import DataSource, OAuthConnectionState
from app.organizations.models import Membership, MembershipRole

GOOGLE_DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"


class GoogleOAuthUnavailable(RuntimeError): pass
class GoogleOAuthInvalid(ValueError): pass
class GoogleAccessDenied(PermissionError): pass
class GoogleRemoteUnauthorized(RuntimeError): pass

logger = logging.getLogger("document_intelligence.integration")


@dataclass(frozen=True)
class GoogleCredentials:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None


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


class GoogleDrivePort(Protocol):
    def authorization_url(self, *, state: str, scope: str) -> str: ...
    def exchange_code(self, *, code: str) -> GoogleCredentials: ...
    def account_email(self, *, credentials: GoogleCredentials) -> str | None: ...
    def list_folders(self, *, credentials: GoogleCredentials) -> list[RemoteFolder]: ...

class GoogleDriveOAuthClient:
    def __init__(self, *, client_id: str | None, client_secret: str | None, redirect_uri: str | None): self.client_id,self.client_secret,self.redirect_uri=client_id,client_secret,redirect_uri
    def _configured(self) -> None:
        if not self.client_id or not self.client_secret or not self.redirect_uri: raise GoogleOAuthUnavailable("Google OAuth is not configured")
    def authorization_url(self, *, state: str, scope: str) -> str:
        self._configured(); return "https://accounts.google.com/o/oauth2/v2/auth?"+urlencode({"client_id":self.client_id,"redirect_uri":self.redirect_uri,"response_type":"code","scope":scope,"state":state,"access_type":"offline","prompt":"consent"})
    def exchange_code(self, *, code: str) -> GoogleCredentials:
        self._configured(); response=httpx.post("https://oauth2.googleapis.com/token",data={"code":code,"client_id":self.client_id,"client_secret":self.client_secret,"redirect_uri":self.redirect_uri,"grant_type":"authorization_code"},timeout=10); 
        if response.status_code in {400,401,403}: raise GoogleOAuthInvalid("Google authorization failed")
        response.raise_for_status(); data=response.json(); return GoogleCredentials(data["access_token"],data.get("refresh_token"),None)
    def account_email(self, *, credentials: GoogleCredentials) -> str | None:
        response = httpx.get(
            "https://www.googleapis.com/drive/v3/about",
            params={"fields": "user(emailAddress)"},
            headers={"Authorization": f"Bearer {credentials.access_token}"},
            timeout=10,
        )
        if response.status_code in {401, 403}:
            raise GoogleRemoteUnauthorized()
        response.raise_for_status()
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
            folders.extend(RemoteFolder(item["id"], item["name"], tuple(item.get("parents", []))) for item in data.get("files", []))
            page_token = data.get("nextPageToken")
            if page_token is None:
                return folders

    def list_folder_files(self, *, credentials: GoogleCredentials, root_folder_id: str) -> list[RemoteFile]:
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
                    fields="nextPageToken,files(id,name,mimeType,modifiedTime,webViewLink,parents)",
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
                            source_url=item.get("webViewLink") or f"https://drive.google.com/open?id={item['id']}",
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

    def _list_nonfolder_files(self, *, credentials: GoogleCredentials, query: str) -> list[RemoteFile]:
        files: list[RemoteFile] = []
        page_token: str | None = None
        while True:
            response = self._list_response(
                credentials=credentials,
                query=f"{query} and mimeType != 'application/vnd.google-apps.folder'",
                fields="nextPageToken,files(id,name,mimeType,modifiedTime,webViewLink,parents)",
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
            source_url=str(item.get("webViewLink") or f"https://drive.google.com/open?id={item['id']}"),
            modified_at=datetime.fromisoformat(str(modified)) if modified else None,
            parent_ids=tuple(str(parent) for parent in item.get("parents", [])),
        )

    @staticmethod
    def _list_response(*, credentials: GoogleCredentials, query: str, fields: str, page_token: str | None) -> httpx.Response:
        response = httpx.get(
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
        if response.status_code in {401, 403}:
            raise GoogleRemoteUnauthorized()
        response.raise_for_status()
        return response

    def read_file(self, *, credentials: GoogleCredentials, remote_file: RemoteFile) -> bytes:
        if remote_file.mime_type == "application/vnd.google-apps.document":
            url = f"https://www.googleapis.com/drive/v3/files/{remote_file.id}/export"
            response = httpx.get(
                url,
                params={"mimeType": "text/plain"},
                headers={"Authorization": f"Bearer {credentials.access_token}"},
                timeout=30,
            )
        else:
            response = httpx.get(
                f"https://www.googleapis.com/drive/v3/files/{remote_file.id}",
                params={"alt": "media"},
                headers={"Authorization": f"Bearer {credentials.access_token}"},
                timeout=30,
            )
        if response.status_code in {401, 403}:
            raise GoogleRemoteUnauthorized()
        response.raise_for_status()
        return response.content


class CredentialCipher:
    def __init__(self, key: str | None): self.key = key
    def encrypt(self, credentials: GoogleCredentials) -> str:
        if not self.key: raise GoogleOAuthUnavailable("Google token encryption is not configured")
        payload = "|".join([credentials.access_token, credentials.refresh_token or "", credentials.expires_at.isoformat() if credentials.expires_at else ""])
        return Fernet(self.key.encode()).encrypt(payload.encode()).decode()
    def decrypt(self, value: str) -> GoogleCredentials:
        if not self.key: raise GoogleOAuthUnavailable("Google token encryption is not configured")
        try: access, refresh, expires = Fernet(self.key.encode()).decrypt(value.encode()).decode().split("|", 2)
        except (InvalidToken, ValueError) as error: raise GoogleOAuthInvalid("credential unavailable") from error
        return GoogleCredentials(access, refresh or None, datetime.fromisoformat(expires) if expires else None)


class GoogleConnectionService:
    def __init__(self, session: Session, cipher: CredentialCipher): self.session, self.cipher = session, cipher
    def require_admin(self, *, scope: OrganizationScope, user_id: UUID) -> None:
        member = self.session.scalar(select(Membership).where(Membership.organization_id == scope.organization_id, Membership.user_id == user_id, Membership.is_active.is_(True), Membership.role.in_([MembershipRole.OWNER, MembershipRole.ADMIN])))
        if member is None: raise GoogleAccessDenied("integration access denied")
    def begin(self, *, scope: OrganizationScope, user_id: UUID, session_secret: str, port: GoogleDrivePort, reauth_source_id: UUID | None = None) -> str:
        self.require_admin(scope=scope, user_id=user_id)
        if reauth_source_id is not None and self.session.scalar(select(DataSource).where(DataSource.id == reauth_source_id, DataSource.organization_id == scope.organization_id, DataSource.provider == "google_drive")) is None:
            raise GoogleAccessDenied("source access denied")
        raw = secrets.token_urlsafe(32)
        self.session.add(OAuthConnectionState(organization_id=scope.organization_id, user_id=user_id, source_id=reauth_source_id, session_hash=hash_secret(session_secret), state_hash=hash_secret(raw), expires_at=datetime.now(UTC) + timedelta(minutes=10)))
        self.session.flush()
        url = port.authorization_url(state=raw, scope=GOOGLE_DRIVE_READONLY_SCOPE)
        logger.info("google connection started", extra={"event":"google_connection","provider":"google_drive","action":"start","result":"redirected","elapsed_ms":0.0})
        return url
    def complete(self, *, raw_state: str, code: str, session_secret: str, port: GoogleDrivePort) -> DataSource:
        state = self.session.scalar(select(OAuthConnectionState).where(OAuthConnectionState.state_hash == hash_secret(raw_state), OAuthConnectionState.consumed_at.is_(None), OAuthConnectionState.expires_at > datetime.now(UTC)))
        active_session = self.session.scalar(select(UserSession).where(UserSession.secret_hash == hash_secret(session_secret), UserSession.user_id == state.user_id if state else False, UserSession.revoked_at.is_(None), UserSession.expires_at > datetime.now(UTC))) if state else None
        if state is None or state.session_hash != hash_secret(session_secret) or active_session is None: raise GoogleOAuthInvalid("OAuth state is invalid")
        self.require_admin(scope=OrganizationScope(state.organization_id), user_id=state.user_id)
        started=time.perf_counter()
        try:
            credentials = port.exchange_code(code=code)
            account_email = port.account_email(credentials=credentials)
        except Exception:
            logger.warning("google connection failed",extra={"event":"google_connection","provider":"google_drive","action":"complete","result":"failed","elapsed_ms":round((time.perf_counter()-started)*1000,2)})
            raise
        source = self.session.scalar(select(DataSource).where(DataSource.id == state.source_id, DataSource.organization_id == state.organization_id)) if state.source_id else None
        if source is None:
            source = DataSource(organization_id=state.organization_id, provider="google_drive", encrypted_credentials=self.cipher.encrypt(credentials), status="connected", account_email=account_email, connected_by_user_id=state.user_id)
            self.session.add(source)
        else:
            source.encrypted_credentials = self.cipher.encrypt(credentials)
            source.status = "connected"
            source.account_email = account_email
            source.connected_by_user_id = state.user_id
        state.consumed_at = datetime.now(UTC)
        self.session.flush(); logger.info("google connection complete",extra={"event":"google_connection","provider":"google_drive","action":"complete","result":"connected","elapsed_ms":round((time.perf_counter()-started)*1000,2)}); return source
    def sources(self, *, scope: OrganizationScope, user_id: UUID) -> list[DataSource]:
        self.require_admin(scope=scope, user_id=user_id)
        return list(self.session.scalars(select(DataSource).where(DataSource.organization_id == scope.organization_id).order_by(DataSource.created_at, DataSource.id)))
    def disconnect(self, *, scope: OrganizationScope, user_id: UUID, source_id: UUID) -> DataSource:
        self.require_admin(scope=scope, user_id=user_id)
        source = self.session.scalar(
            select(DataSource).where(
                DataSource.id == source_id,
                DataSource.organization_id == scope.organization_id,
                DataSource.provider == "google_drive",
            )
        )
        if source is None:
            raise GoogleAccessDenied("source access denied")
        source.encrypted_credentials = None
        source.account_email = None
        source.status = "disconnected"
        self.session.execute(
            update(OAuthConnectionState)
            .where(
                OAuthConnectionState.source_id == source.id,
                OAuthConnectionState.consumed_at.is_(None),
            )
            .values(consumed_at=datetime.now(UTC))
        )
        self.session.add(
            AuditLog(
                organization_id=scope.organization_id,
                actor_user_id=user_id,
                action="data_source.disconnected",
                target_type="data_source",
                target_id=source.id,
            )
        )
        self.session.flush()
        logger.info("google source disconnected", extra={"event":"google_connection","provider":"google_drive","action":"disconnect","result":"disconnected","elapsed_ms":0.0})
        return source
    def folders(self, *, scope: OrganizationScope, user_id: UUID, source_id: UUID, port: GoogleDrivePort) -> list[RemoteFolder]:
        self.require_admin(scope=scope, user_id=user_id)
        source = self.session.scalar(select(DataSource).where(DataSource.id == source_id, DataSource.organization_id == scope.organization_id, DataSource.status == "connected"))
        if source is None: raise GoogleAccessDenied("source access denied")
        try: return port.list_folders(credentials=self.cipher.decrypt(source.encrypted_credentials))
        except GoogleRemoteUnauthorized:
            source.status = "reauth_required"; self.session.flush()
            logger.warning("google source requires reauthentication",extra={"event":"google_connection","provider":"google_drive","action":"list_folders","result":"reauth_required","elapsed_ms":0.0})
            raise GoogleOAuthInvalid("source requires reauthentication")
