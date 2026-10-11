"""On-demand access to the original file behind a document, through its source connector.

Nothing is stored: the connector downloads into a temp file that the HTTP layer streams to the browser
and closes. Only the viewer types the web app can render are served; everything else uses extracted text.
"""
from collections.abc import Callable
from dataclasses import dataclass
from typing import IO, Any
from uuid import UUID

import httpx
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.ingestion.extraction.mime import DOCX, GOOGLE_DOC, PDF, SHEETS, SLIDES
from app.integrations.errors import SourceItemUnavailable, SourceRemoteUnauthorized
from app.integrations.google_drive import GoogleItemTooLarge, RemoteFile
from app.integrations.http import DownloadIntegrityError, RemoteFileTooLarge, RemoteThrottled
from app.integrations.models import DataSource
from app.integrations.registry import IntegrationRegistry
from app.knowledge.models import Document

GOOGLE_NATIVE = {GOOGLE_DOC, SHEETS, SLIDES}
SERVED_BINARY = {PDF, DOCX}
MICROSOFT_PROVIDERS = {"onedrive", "sharepoint"}


class FileAccessError(Exception):
    """A user-presentable failure; `code` is the stable contract with the frontend."""

    def __init__(self, status_code: int, code: str, *, retry_after: int | None = None):
        super().__init__(code)
        self.status_code, self.code, self.retry_after = status_code, code, retry_after


@dataclass
class OpenedFile:
    stream: IO[bytes]
    content_type: str
    size: int
    filename: str


def servable_content_type(document: Document, provider: str) -> tuple[str, bool] | None:
    """(content type to serve, needs Google export) or None when the web viewer cannot render this file."""
    if provider == "google_drive" and document.mime_type in GOOGLE_NATIVE:
        return PDF, True
    if provider in {"google_drive", *MICROSOFT_PROVIDERS} and document.mime_type in SERVED_BINARY:
        return document.mime_type, False
    return None


def _stream_size(stream: IO[bytes]) -> int:
    stream.seek(0, 2)
    size = stream.tell()
    stream.seek(0)
    return size


class DocumentFileFetcher:
    def __init__(self, settings: Settings, session: Session, *, provider_factory: Callable[[str, UUID], Any] | None = None):
        self.session = session
        self._factory = provider_factory or (
            lambda key, source_id: IntegrationRegistry(settings).get(key, session=session, source_id=source_id)._provider
        )

    def open(self, document: Document, source: DataSource) -> OpenedFile:
        served = servable_content_type(document, source.provider)
        if served is None:
            raise FileAccessError(415, "viewer_not_supported")
        if not source.encrypted_credentials or source.status != "connected":
            raise FileAccessError(409, "source_access_denied")
        content_type, export = served
        try:
            stream = self._download(document, source, export)
        except FileAccessError:
            raise
        except RemoteThrottled as error:
            raise FileAccessError(429, "source_throttled", retry_after=int(error.retry_after_seconds or 30)) from error
        except RemoteFileTooLarge as error:
            raise FileAccessError(413, "file_too_large") from error
        except SourceRemoteUnauthorized as error:
            raise FileAccessError(409, "source_access_denied") from error
        except GoogleItemTooLarge as error:
            raise FileAccessError(413, "file_too_large") from error
        except SourceItemUnavailable as error:
            raise FileAccessError(404, "source_file_unavailable") from error
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if status == 404:
                raise FileAccessError(404, "source_file_missing") from error
            if status in {401, 403}:
                raise FileAccessError(409, "source_access_denied") from error
            raise FileAccessError(502, "source_unavailable") from error
        except (httpx.HTTPError, DownloadIntegrityError) as error:
            raise FileAccessError(502, "source_unavailable") from error
        name = document.name if not export else f"{document.name}.pdf"
        return OpenedFile(stream, content_type, _stream_size(stream), name)

    def _download(self, document: Document, source: DataSource, export: bool) -> IO[bytes]:
        provider = self._factory(source.provider, source.id)
        if source.provider == "google_drive":
            def call(credentials):
                if export:
                    return provider.client.export_pdf(credentials=credentials, file_id=document.external_file_id)
                return provider.client.read_file(credentials=credentials, remote_file=RemoteFile(
                    id=document.external_file_id, name=document.name, mime_type=document.mime_type,
                    source_url=document.source_url, modified_at=None,
                ))
            return provider._remote_call(source.encrypted_credentials, call)
        credentials = provider._credentials(source.encrypted_credentials)
        try:
            return provider.client.read_file(credentials=credentials, item_id=document.external_file_id)
        finally:
            self._persist_refreshed(provider, source)

    def preview_url(self, document: Document, source: DataSource, page: int | None) -> str | None:
        """Graph Office preview (work/school only). Never raises for 'cannot preview'; returns None."""
        if source.provider not in MICROSOFT_PROVIDERS or document.mime_type not in SERVED_BINARY:
            return None
        if not source.encrypted_credentials or source.status != "connected":
            return None
        provider = self._factory(source.provider, source.id)
        try:
            credentials = provider._credentials(source.encrypted_credentials)
            try:
                return provider.client.preview_url(credentials=credentials, item_id=document.external_file_id, page=page)
            finally:
                self._persist_refreshed(provider, source)
        except (SourceRemoteUnauthorized, RemoteThrottled, httpx.HTTPError, ValueError):
            return None

    def _persist_refreshed(self, provider: Any, source: DataSource) -> None:
        refreshed = getattr(provider, "updated_encrypted_credentials", None)
        if refreshed and refreshed != source.encrypted_credentials:
            source.encrypted_credentials = refreshed
            self.session.commit()
