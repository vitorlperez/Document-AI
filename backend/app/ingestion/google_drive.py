"""Google Drive discovery and text extraction behind the ingestion boundary."""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from zipfile import BadZipFile

from docx import Document as DocxDocument
from docx.opc.exceptions import PackageNotFoundError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.ingestion.service import ELIGIBLE_MIME_TYPES, DiscoveredDocument
from app.integrations.google_drive import (
    CredentialCipher,
    GoogleCredentials,
    GoogleDriveOAuthClient,
    GoogleRemoteUnauthorized,
    RemoteFile,
    RemoteFolder,
)
from app.workspaces.models import WorkspaceFolderSelection

MAX_EXTRACTION_WORKERS = 6


class GoogleDriveDocumentProvider:
    """Fetch an authorized scope union, then retain extracted text only in the DB."""

    def __init__(
        self,
        client: GoogleDriveOAuthClient,
        cipher: CredentialCipher,
        *,
        extraction_workers: int = MAX_EXTRACTION_WORKERS,
    ):
        self.client = client
        self.cipher = cipher
        self.extraction_workers = min(MAX_EXTRACTION_WORKERS, max(1, extraction_workers))

    def discover(
        self,
        *,
        encrypted_credentials: str,
        selections: list[WorkspaceFolderSelection],
    ) -> list[DiscoveredDocument]:
        credentials = self.cipher.decrypt(encrypted_credentials)
        remote_files: dict[str, RemoteFile] = {}
        for selection in selections:
            if selection.kind == "folder":
                found = self.client.list_folder_files(
                    credentials=credentials,
                    root_folder_id=selection.external_folder_id,
                )
            elif selection.kind == "root_files":
                found = self.client.list_root_files(credentials=credentials)
            elif selection.kind == "all_accessible":
                found = self.client.list_all_files(credentials=credentials)
            else:
                raise ValueError("unsupported workspace selection")
            for remote_file in found:
                remote_files.setdefault(remote_file.id, remote_file)
        # A Drive response does not promise an implicit ordering. Stable IDs
        # make repeated full snapshots and the concurrent projection predictable.
        files = sorted(remote_files.values(), key=lambda remote_file: remote_file.id)
        if not files:
            return []
        # Only remote reads and parsing happen on threads. The caller keeps all
        # SQLAlchemy access in the Celery worker thread after this returns.
        with ThreadPoolExecutor(max_workers=min(self.extraction_workers, len(files))) as executor:
            return list(
                executor.map(
                    lambda remote_file: self._extract(credentials=credentials, remote_file=remote_file),
                    files,
                )
            )

    def folders(self, *, encrypted_credentials: str) -> list[RemoteFolder]:
        """Return safe folder metadata for the Company Library projection.

        This is intentionally separate from extraction: the library retains no
        provider credentials and does not browse Drive during a user request.
        """
        return self.client.list_folders(credentials=self.cipher.decrypt(encrypted_credentials))

    def _extract(self, *, credentials: GoogleCredentials, remote_file: RemoteFile) -> DiscoveredDocument:
        base = {
            "external_file_id": remote_file.id,
            "name": remote_file.name,
            "mime_type": remote_file.mime_type,
            "source_url": remote_file.source_url,
            "modified_at": remote_file.modified_at,
            "parent_ids": remote_file.parent_ids,
        }
        if remote_file.mime_type not in ELIGIBLE_MIME_TYPES:
            return DiscoveredDocument(**base)
        try:
            content = self.client.read_file(credentials=credentials, remote_file=remote_file)
            text = _extract_text(remote_file.mime_type, content)
        except GoogleRemoteUnauthorized:
            # A listing token can remain valid while one shared/export-restricted
            # file rejects its content request. Treat that as an item failure;
            # source-level authorization failures are still raised by discovery.
            return DiscoveredDocument(**base, error_code="source_file_unavailable")
        except (BadZipFile, PackageNotFoundError, PdfReadError, UnicodeDecodeError, ValueError):
            # Do not attach the remote body or exception to records/logs. The
            # document's explicit code is enough for an Admin to retry safely.
            return DiscoveredDocument(**base, error_code="text_extraction_failed")
        return DiscoveredDocument(**base, text=text)


def _extract_text(mime_type: str, content: bytes) -> str:
    if mime_type == "application/vnd.google-apps.document":
        return content.decode("utf-8")
    if mime_type == "application/pdf":
        return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages)
    if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return "\n".join(paragraph.text for paragraph in DocxDocument(BytesIO(content)).paragraphs)
    raise ValueError("unsupported file type")
