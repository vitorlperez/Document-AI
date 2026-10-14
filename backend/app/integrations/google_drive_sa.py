"""Organization robot credentials and read-only Drive port; never OAuth consent."""

import json
import re
import tempfile
import threading
import time
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
from cryptography.fernet import InvalidToken

from app.integrations.errors import SourceItemUnavailable
from app.integrations.google_drive import (
    DAILY_QUOTA_REASONS,
    GOOGLE_DRIVE_READONLY_SCOPE,
    ITEM_FORBIDDEN_REASONS,
    QUOTA_REASONS,
    GoogleCredentials,
    GoogleCursorInvalid,
    GoogleDriveOAuthClient,
    RemoteFolder,
    _google_retryable,
    google_error_reason,
)
from app.integrations.http import RemoteHttp, RemoteThrottled, parse_retry_after
from app.integrations.keyring import build_fernet

FOLDER_MIME = "application/vnd.google-apps.folder"
METADATA_FIELDS = "id,name,mimeType,trashed,parents,capabilities(canDownload),sharingUser(emailAddress),sharedWithMeTime,driveId"
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{10,128}$")


class FolderAccessLost(RuntimeError):
    def __init__(self, folder_id=None):
        super().__init__("not_shared")
        self.folder_id = folder_id


class RobotUnavailable(RuntimeError):
    pass


class SaRequestError(RuntimeError):
    def __init__(self, code, status=422):
        super().__init__(code)
        self.code, self.status = code, status


def parse_folder_id(value):
    value = value.strip()
    if ID_PATTERN.fullmatch(value):
        return value
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.netloc != "drive.google.com":
        raise ValueError("invalid_folder_link")
    match = re.fullmatch(
        r"/(?:a/[^/]+/)?(?:drive/)?(?:u/\d+/|mobile/)?folders/([A-Za-z0-9_-]{10,128})/?",
        parsed.path,
    )
    if match:
        return match.group(1)
    if parsed.path in ("/open", "/folderview"):
        folder_id = parse_qs(parsed.query).get("id", [""])[0]
        if ID_PATTERN.fullmatch(folder_id):
            return folder_id
    raise ValueError("invalid_folder_link")


def raise_for_sa(response, *, root=False):
    status = response.status_code
    reason = google_error_reason(response)
    if status == 401:
        raise RobotUnavailable("robot_unavailable")
    if status == 429 or (status == 403 and reason in QUOTA_REASONS | DAILY_QUOTA_REASONS):
        raise RemoteThrottled(parse_retry_after(response.headers.get("Retry-After")))
    if root and status in (403, 404):
        raise FolderAccessLost()
    if status == 404 or (status == 403 and reason in ITEM_FORBIDDEN_REASONS):
        raise SourceItemUnavailable("source_file_unavailable")
    if status == 403:
        raise RobotUnavailable("robot_unavailable")
    if status >= 400:
        # Sanitized error: never expose the Google error body or authorization headers.
        raise SaRequestError("provider_unavailable", 503)


class ServiceAccountKeyCipher:
    def __init__(self, key, *, fallback_keys=()):
        self.fernet = build_fernet([key, *fallback_keys])

    def encrypt(self, key):
        if not self.fernet:
            raise RobotUnavailable("robot_unavailable")
        return self.fernet.encrypt(json.dumps(key).encode()).decode()

    def decrypt(self, value):
        try:
            if not self.fernet:
                raise RobotUnavailable("robot_unavailable")
            return json.loads(self.fernet.decrypt(value.encode()))
        except (InvalidToken, ValueError, TypeError, AttributeError):
            raise RobotUnavailable("robot_unavailable") from None


class ServiceAccountTokenSource:
    """Process-local token cache with a lock shared by extraction threads (PoC §7)."""

    def __init__(self, encrypted_key, cipher, *, http=None, clock=time.time):
        self.encrypted_key, self.cipher = encrypted_key, cipher
        self.http, self.clock = http or RemoteHttp(), clock
        self._cached = None
        self._lock = threading.Lock()

    def credentials(self):
        with self._lock:
            now = self.clock()
            if self._cached and self._cached.expires_at.timestamp() > now + 120:
                return self._cached
            try:
                key = self.cipher.decrypt(self.encrypted_key)
                assertion = jwt.encode(
                    {
                        "iss": key["client_email"],
                        "scope": GOOGLE_DRIVE_READONLY_SCOPE,
                        "aud": "https://oauth2.googleapis.com/token",
                        "iat": int(now) - 30,
                        "exp": int(now) + 3570,
                    },
                    key["private_key"],
                    algorithm="RS256",
                    headers={"kid": key["private_key_id"]},
                )
                reply = self.http.request(
                    "POST",
                    "https://oauth2.googleapis.com/token",
                    data={
                        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                        "assertion": assertion,
                    },
                    timeout=20,
                )
                data = reply.json()
                token = data.get("access_token")
                expires = int(data.get("expires_in", 0))
                if (
                    reply.status_code != 200
                    or not isinstance(token, str)
                    or not token
                    or expires <= 120
                ):
                    raise RobotUnavailable("robot_unavailable")
                self._cached = GoogleCredentials(
                    token, None, datetime.fromtimestamp(now + expires, UTC)
                )
                return self._cached
            except (KeyError, ValueError, TypeError, httpx.HTTPError, jwt.PyJWTError):
                raise RobotUnavailable("robot_unavailable") from None


class _SaHttp:
    """Classify SA responses before the legacy Drive reader can apply OAuth semantics."""

    def __init__(self, http):
        self.http = http

    def request(self, method, url, **kwargs):
        params = kwargs.get("params")
        if params and "fields" in params:
            params = dict(params)
            fields = params["fields"]
            if "capabilities" not in fields:
                fields = fields.replace("md5Checksum", "md5Checksum,capabilities(canDownload)")
            params["fields"] = fields
            kwargs["params"] = params
        response = self.http.request(method, url, **kwargs)
        if "/changes" in url and response.status_code in (400, 410):
            raise GoogleCursorInvalid("cursor_expired")
        raise_for_sa(response)
        return response

    def download_to(self, url, dest, **kwargs):
        kwargs["on_error"] = raise_for_sa
        return self.http.download_to(url, dest, **kwargs)


class SaDriveClient:
    """Exposes only Drive read methods. It has no authorization/refresh/write interface."""

    def __init__(self, *, http=None):
        self.http = http or RemoteHttp(is_retryable=_google_retryable)
        self.reader = GoogleDriveOAuthClient(
            client_id=None, client_secret=None, redirect_uri=None, http=_SaHttp(self.http)
        )

    _remote_file = staticmethod(GoogleDriveOAuthClient._remote_file)

    def metadata(self, *, credentials, file_id, root=True):
        if not ID_PATTERN.fullmatch(file_id):
            raise ValueError("invalid_folder_link")
        response = self.http.request(
            "GET",
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            params={"fields": METADATA_FIELDS, "supportsAllDrives": "true"},
            headers={"Authorization": f"Bearer {credentials.access_token}"},
            timeout=20,
        )
        try:
            raise_for_sa(response, root=root)
        except FolderAccessLost:
            raise FolderAccessLost(file_id) from None
        item = response.json()
        if item.get("trashed"):
            raise FolderAccessLost(file_id)
        return item

    def verify_folder(self, *, credentials, folder_id):
        root = self.metadata(credentials=credentials, file_id=folder_id)
        if root.get("mimeType") != FOLDER_MIME:
            raise SaRequestError("not_a_folder")
        pending = [(root, 0)]
        visited = set()
        while pending:
            item, depth = pending.pop()
            if item.get("id") in visited:
                continue
            visited.add(item.get("id"))
            if item.get("sharedWithMeTime"):
                return root, item
            if depth < 10:
                for parent in item.get("parents", []):
                    pending.append(
                        (self.metadata(credentials=credentials, file_id=parent), depth + 1)
                    )
        raise FolderAccessLost(folder_id)

    def inbox(self, *, credentials):
        return self._list(
            credentials,
            "sharedWithMe and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
            METADATA_FIELDS,
        )

    def _list(self, credentials, query, fields):
        token, items = None, []
        while True:
            response = self.reader._list_response(
                credentials=credentials,
                query=query,
                fields=f"nextPageToken,files({fields})",
                page_token=token,
            )
            payload = response.json()
            items.extend(payload.get("files", []))
            token = payload.get("nextPageToken")
            if not token:
                return items

    def list_folders(self, *, credentials):
        return [
            RemoteFolder(str(x["id"]), str(x["name"]), tuple(x.get("parents", [])))
            for x in self._list(
                credentials,
                "mimeType = 'application/vnd.google-apps.folder' and trashed = false",
                "id,name,parents",
            )
        ]

    def list_folder_files(self, *, credentials, root_folder_id):
        self.verify_folder(credentials=credentials, folder_id=root_folder_id)
        pending, visited, files = [root_folder_id], set(), []
        while pending:
            folder = pending.pop()
            if folder in visited:
                continue
            visited.add(folder)
            # Never enumerate a parent before checking access with files.get.
            self.metadata(credentials=credentials, file_id=folder)
            for item in self._list(
                credentials,
                f"'{folder}' in parents and trashed = false",
                "id,name,mimeType,modifiedTime,webViewLink,parents,size,md5Checksum,capabilities(canDownload)",
            ):
                if item["mimeType"] == FOLDER_MIME:
                    pending.append(item["id"])
                elif item["mimeType"] != "application/vnd.google-apps.shortcut":
                    files.append(self._remote_file(item))
        return files

    def start_page_token(self, **kwargs):
        return self.reader.start_page_token(**kwargs)

    def changes(self, **kwargs):
        return self.reader.changes(**kwargs)

    def get_file(self, **kwargs):
        return self.reader.get_file(**kwargs)

    def export_pdf(self, **kwargs):
        return self.reader.export_pdf(**kwargs)

    def read_file(self, *, credentials, remote_file):
        from app.ingestion.extraction.mime import GOOGLE_EXPORT_MIME

        if remote_file.can_download is False:
            raise SourceItemUnavailable("source_file_unavailable")
        mime = GOOGLE_EXPORT_MIME.get(remote_file.mime_type)
        if not mime:
            return self.reader.read_file(credentials=credentials, remote_file=remote_file)
        response = self.http.request(
            "GET",
            f"https://www.googleapis.com/drive/v3/files/{remote_file.id}/export",
            params={"mimeType": mime},
            headers={"Authorization": f"Bearer {credentials.access_token}"},
            timeout=30,
        )
        fallback = (
            google_error_reason(response) == "exportSizeLimitExceeded"
            and response.status_code == 403
        )
        if fallback:
            response = self.http.request(
                "GET",
                f"https://www.googleapis.com/drive/v3/files/{remote_file.id}/export",
                params={"mimeType": "text/plain"},
                headers={"Authorization": f"Bearer {credentials.access_token}"},
                timeout=30,
            )
        raise_for_sa(response)
        content = tempfile.TemporaryFile()  # noqa: SIM115 - caller owns this file
        try:
            content.write(response.content)
            content.seek(0)
            if fallback:
                content.extraction_mime_type = "text/plain"
            return content
        except BaseException:
            content.close()
            raise
