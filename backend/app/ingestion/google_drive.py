"""Google Drive discovery and text extraction behind the ingestion boundary."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zipfile import BadZipFile

from docx.opc.exceptions import PackageNotFoundError
from pypdf.errors import PdfReadError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.extraction import BASE_MIME_TYPES, extract_blocks
from app.ingestion.extraction.errors import ExtractionError
from app.ingestion.extraction.mime import normalize_mime_type
from app.ingestion.service import (
    DiscoveredDocument,
    DiscoveryResult,
    ExtractedBlock,
)
from app.integrations.errors import SourceItemUnavailable
from app.integrations.google_drive import (
    CredentialCipher,
    GoogleCredentials,
    GoogleCursorInvalid,
    GoogleDriveOAuthClient,
    GoogleRemoteUnauthorized,
    RemoteFile,
    RemoteFolder,
)
from app.integrations.models import DataSource
from app.workspaces.models import WorkspaceFolderSelection

MAX_EXTRACTION_WORKERS = 6
REFRESH_SAFETY_MARGIN = timedelta(minutes=2)


class GoogleDriveDocumentProvider:
    """Fetch an authorized scope union, then retain extracted text only in the DB."""

    def __init__(
        self,
        client: GoogleDriveOAuthClient,
        cipher: CredentialCipher,
        *,
        extraction_workers: int = MAX_EXTRACTION_WORKERS,
        session: Session | None = None,
        source_id: UUID | None = None,
        ocr=None,
        budget=None,
    ):
        self.ocr, self.budget = ocr, budget
        self.client = client
        self.cipher = cipher
        self.extraction_workers = min(MAX_EXTRACTION_WORKERS, max(1, extraction_workers))
        self.session = session
        self.source_id = source_id
        self._folder_catalog: tuple[str, list[RemoteFolder]] | None = None
        self._credentials: GoogleCredentials | None = None
        self.updated_encrypted_credentials: str | None = None

    def discover(
        self,
        *,
        encrypted_credentials: str,
        selections: list[WorkspaceFolderSelection],
        force_file_ids: set[str] | None = None,
        force_full: bool = False,
    ) -> DiscoveryResult:
        self._folder_catalog = None
        links: dict[UUID, str | None] = {}
        # The first run (or a newly added selection) takes a complete snapshot.
        # Capture cursors first so edits during enumeration are picked up next run.
        if force_full or any(not selection.encrypted_delta_link for selection in selections):
            for selection in selections:
                links[selection.id] = self._remote_call(
                    encrypted_credentials,
                    lambda credentials: self.client.start_page_token(credentials=credentials),
                )
            return DiscoveryResult(
                documents=self._snapshot(encrypted_credentials, selections),
                delta_links=links,
                full_snapshot=True,
            )

        try:
            folders = (
                self._remote_call(
                    encrypted_credentials,
                    lambda credentials: self.client.list_folders(credentials=credentials),
                )
                if any(selection.kind == "folder" for selection in selections)
                else []
            )
            if any(selection.kind == "folder" for selection in selections):
                self._folder_catalog = (encrypted_credentials, folders)
            root_file_ids = (
                {
                    item.id
                    for item in self._remote_call(
                        encrypted_credentials,
                        lambda credentials: self.client.list_root_files(credentials=credentials),
                    )
                }
                if any(selection.kind == "root_files" for selection in selections)
                else set()
            )
            descendants: dict[str, set[str]] = {}
            children: dict[str, set[str]] = {}
            for folder in folders:
                for parent_id in folder.parent_ids:
                    children.setdefault(parent_id, set()).add(folder.id)
            for selection in selections:
                if selection.kind != "folder":
                    continue
                included = {selection.external_folder_id}
                pending = [selection.external_folder_id]
                while pending:
                    parent_id = pending.pop()
                    for child_id in children.get(parent_id, set()) - included:
                        included.add(child_id)
                        pending.append(child_id)
                descendants[selection.external_folder_id] = included

            def in_scope(file_id: str, remote_file: RemoteFile) -> bool:
                return any(
                    selection.kind == "all_accessible"
                    or (selection.kind == "root_files" and file_id in root_file_ids)
                    or (
                        selection.kind == "folder"
                        and bool(
                            descendants.get(selection.external_folder_id, set())
                            & set(remote_file.parent_ids)
                        )
                    )
                    for selection in selections
                )

            changes_by_id: dict[str, RemoteFile] = {}
            removed: set[str] = set()
            folder_changed = False
            for selection in selections:
                cursor = self.cipher.decrypt_cursor(selection.encrypted_delta_link)
                page = self._remote_call(
                    encrypted_credentials,
                    lambda credentials: self.client.changes(
                        credentials=credentials, page_token=cursor
                    ),
                )
                links[selection.id] = page.new_start_page_token
                for change in page.changes:
                    file_id = str(change.get("fileId") or "")
                    item = change.get("file")
                    if not file_id:
                        continue
                    if change.get("removed") or not isinstance(item, dict) or item.get("trashed"):
                        # A removed folder may contain indexed descendants that
                        # are absent from the change feed. Reconcile the scope.
                        folder_changed = True
                        removed.add(file_id)
                        changes_by_id.pop(file_id, None)
                        continue
                    remote_file = self.client._remote_file(item)
                    if remote_file.mime_type == "application/vnd.google-apps.folder":
                        folder_changed = True
                        continue
                    if in_scope(file_id, remote_file):
                        changes_by_id[file_id] = remote_file
                        removed.discard(file_id)
                    else:
                        removed.add(file_id)
            for file_id in force_file_ids or set():
                if file_id in removed or file_id in changes_by_id:
                    continue
                try:
                    remote_file = self._remote_call(
                        encrypted_credentials,
                        lambda credentials: self.client.get_file(
                            credentials=credentials, file_id=file_id
                        ),
                    )
                except SourceItemUnavailable:
                    removed.add(file_id)
                    continue
                if remote_file is None or not in_scope(file_id, remote_file):
                    removed.add(file_id)
                    continue
                changes_by_id[file_id] = remote_file
            if folder_changed:
                # Changes to folder ancestry can affect every descendant; a
                # full reconciliation safely handles moves into and out of scope.
                self._folder_catalog = None
                links = {
                    selection.id: self._remote_call(
                        encrypted_credentials,
                        lambda credentials: self.client.start_page_token(
                            credentials=credentials
                        ),
                    )
                    for selection in selections
                }
                return DiscoveryResult(
                    documents=self._snapshot(encrypted_credentials, selections),
                    delta_links=links,
                    full_snapshot=True,
                )
            result = self._extract_files(encrypted_credentials, changes_by_id.values())
            return DiscoveryResult(
                documents=result,
                removed_file_ids=tuple(sorted(removed)),
                delta_links=links,
                full_snapshot=False,
            )
        except GoogleCursorInvalid:
            self._folder_catalog = None
            links = {
                selection.id: self._remote_call(
                    encrypted_credentials,
                    lambda credentials: self.client.start_page_token(credentials=credentials),
                )
                for selection in selections
            }
            return DiscoveryResult(
                documents=self._snapshot(encrypted_credentials, selections),
                delta_links=links,
                full_snapshot=True,
            )

    def _snapshot(
        self, encrypted_credentials: str, selections: list[WorkspaceFolderSelection]
    ) -> list[DiscoveredDocument]:
        remote_files: dict[str, RemoteFile] = {}
        for selection in selections:
            if selection.kind == "folder":
                found = self._remote_call(
                    encrypted_credentials,
                    lambda credentials: self.client.list_folder_files(
                        credentials=credentials, root_folder_id=selection.external_folder_id
                    ),
                )
            elif selection.kind == "root_files":
                found = self._remote_call(
                    encrypted_credentials,
                    lambda credentials: self.client.list_root_files(credentials=credentials),
                )
            elif selection.kind == "all_accessible":
                found = self._remote_call(
                    encrypted_credentials,
                    lambda credentials: self.client.list_all_files(credentials=credentials),
                )
            else:
                raise ValueError("unsupported workspace selection")
            for remote_file in found:
                remote_files.setdefault(remote_file.id, remote_file)
        return self._extract_files(encrypted_credentials, remote_files.values())

    def _extract_files(self, encrypted_credentials: str, remote_files) -> list[DiscoveredDocument]:
        files = sorted(remote_files, key=lambda remote_file: remote_file.id)
        if not files:
            return []
        # Only remote reads and parsing happen on threads. The caller keeps all
        # SQLAlchemy access in the Celery worker thread after this returns.
        with ThreadPoolExecutor(max_workers=min(self.extraction_workers, len(files))) as executor:
            return list(
                executor.map(
                    lambda remote_file: self._extract(
                        encrypted_credentials=encrypted_credentials, remote_file=remote_file
                    ),
                    files,
                )
            )

    def folders(self, *, encrypted_credentials: str) -> list[RemoteFolder]:
        """Return safe folder metadata for the Company Library projection.

        This is intentionally separate from extraction: the library retains no
        provider credentials and does not browse Drive during a user request.
        """
        if self._folder_catalog is not None and self._folder_catalog[0] == encrypted_credentials:
            return self._folder_catalog[1]
        folders = self._remote_call(
            encrypted_credentials,
            lambda credentials: self.client.list_folders(credentials=credentials),
        )
        self._folder_catalog = (encrypted_credentials, folders)
        return folders

    def encrypt_delta_link(self, value: str) -> str:
        return self.cipher.encrypt_cursor(value)

    eligible_mime_types = BASE_MIME_TYPES

    def _extract(
        self, *, encrypted_credentials: str, remote_file: RemoteFile
    ) -> DiscoveredDocument:
        mime_type = normalize_mime_type(remote_file.name, remote_file.mime_type)
        base = {
            "external_file_id": remote_file.id,
            "name": remote_file.name,
            "mime_type": mime_type,
            "source_url": remote_file.source_url,
            "modified_at": remote_file.modified_at,
            "parent_ids": remote_file.parent_ids,
        }
        if mime_type not in self.eligible_mime_types:
            return DiscoveredDocument(**base)
        try:
            content = self._remote_call(
                encrypted_credentials,
                lambda credentials: self.client.read_file(
                    credentials=credentials, remote_file=remote_file
                ),
            )
            blocks = extract_blocks(mime_type, content, ocr=self.ocr, budget=self.budget)
        except (GoogleRemoteUnauthorized, SourceItemUnavailable):
            # A listing token can remain valid while one shared/export-restricted
            # file rejects its content request. Treat that as an item failure;
            # source-level authorization failures are still raised by discovery.
            return DiscoveredDocument(**base, error_code="source_file_unavailable")
        except ExtractionError as error:
            return DiscoveredDocument(**base, error_code=error.code)
        except (BadZipFile, PackageNotFoundError, PdfReadError, UnicodeDecodeError, ValueError):
            # Do not attach the remote body or exception to records/logs. The
            # document's explicit code is enough for an Admin to retry safely.
            return DiscoveredDocument(**base, error_code="text_extraction_failed")
        return DiscoveredDocument(**base, text="\n\n".join(block.text for block in blocks), blocks=tuple(blocks))

    @staticmethod
    def _needs_refresh(credentials: GoogleCredentials) -> bool:
        return (
            credentials.expires_at is None
            or credentials.expires_at <= datetime.now(UTC) + REFRESH_SAFETY_MARGIN
        )

    def _remote_call(self, encrypted_credentials: str, call):
        credentials = self._current_credentials(encrypted_credentials)
        try:
            return call(credentials)
        except GoogleRemoteUnauthorized:
            return call(self._refresh_credentials(encrypted_credentials, force=True))

    def _current_credentials(self, encrypted_credentials: str) -> GoogleCredentials:
        if self._credentials is not None:
            if self._needs_refresh(self._credentials):
                return self._refresh_credentials(encrypted_credentials)
            return self._credentials
        credentials = self.cipher.decrypt(encrypted_credentials)
        if self._needs_refresh(credentials):
            return self._refresh_credentials(encrypted_credentials)
        self._credentials = credentials
        return credentials

    def _refresh_credentials(
        self, encrypted_credentials: str, *, force: bool = False
    ) -> GoogleCredentials:
        if self.session is not None and self.source_id is not None:
            source = self.session.scalar(
                select(DataSource)
                .where(DataSource.id == self.source_id)
                .with_for_update()
            )
            if source is None:
                raise GoogleRemoteUnauthorized("Google Drive source is unavailable")
            locked_credentials = source.encrypted_credentials
            credentials = self.cipher.decrypt(locked_credentials)
            if not self._needs_refresh(credentials) and (
                not force or locked_credentials != encrypted_credentials
            ):
                self._credentials = credentials
                self.updated_encrypted_credentials = locked_credentials
                self.session.commit()
                return credentials
        else:
            credentials = self.cipher.decrypt(encrypted_credentials)
        if not credentials.refresh_token:
            raise GoogleRemoteUnauthorized("Google Drive refresh token is unavailable")
        refreshed = self.client.refresh_access_token(refresh_token=credentials.refresh_token)
        encrypted_refreshed = self.cipher.encrypt(refreshed)
        self._credentials = refreshed
        self.updated_encrypted_credentials = encrypted_refreshed
        if self.session is not None and self.source_id is not None:
            source.encrypted_credentials = encrypted_refreshed
            self.session.commit()
        return refreshed


def _extract_blocks(mime_type: str, content: bytes) -> list[ExtractedBlock]:
    return extract_blocks(mime_type, content)


def _markdown_blocks(text: str) -> list[ExtractedBlock]:
    from app.ingestion.extraction.text import markdown_blocks
    return markdown_blocks(text)


def _extract_text(mime_type: str, content: bytes) -> str:
    return "\n\n".join(block.text for block in _extract_blocks(mime_type, content))
