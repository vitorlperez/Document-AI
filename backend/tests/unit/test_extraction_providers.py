from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from test_google_drive_ingestion import (
    FakeGoogleDriveClient,
    encrypted_credentials,
    fresh_credentials,
    selection,
)

from app.ingestion.extraction import BASE_MIME_TYPES, ELIGIBLE_MIME_TYPES
from app.ingestion.extraction.mime import PPTX, SHEETS, SLIDES, XLSX
from app.ingestion.google_drive import GoogleDriveDocumentProvider
from app.integrations.google_drive import GoogleCredentials, GoogleDriveOAuthClient, RemoteFile
from app.integrations.onedrive import OneDriveCredentials, OneDriveDocumentProvider


@pytest.mark.parametrize("mime,export", [(SHEETS, XLSX), (SLIDES, PPTX)])
def test_google_native_formats_export_to_office(mime, export):
    calls = []

    class Http:
        def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            return httpx.Response(200, content=b"data", request=httpx.Request(method, url))

    client = GoogleDriveOAuthClient(
        client_id=None, client_secret=None, redirect_uri=None, http=Http()
    )
    remote = RemoteFile("id", "file", mime, "", None)
    assert (
        client.read_file(
            credentials=GoogleCredentials("token", "refresh", None), remote_file=remote
        ).read()
        == b"data"
    )
    assert calls[0][1].endswith("/id/export")
    assert calls[0][2]["params"] == {"mimeType": export}


def test_google_export_size_limit_is_item_failure():
    from app.integrations.errors import SourceItemUnavailable

    class Http:
        def request(self, method, url, **kwargs):
            return httpx.Response(
                403,
                json={"error": {"errors": [{"reason": "exportSizeLimitExceeded"}]}},
                request=httpx.Request(method, url),
            )

    client = GoogleDriveOAuthClient(
        client_id=None, client_secret=None, redirect_uri=None, http=Http()
    )
    with pytest.raises(SourceItemUnavailable):
        client.read_file(
            credentials=GoogleCredentials("token", "refresh", None),
            remote_file=RemoteFile("id", "file", SHEETS, "", None),
        )


def test_google_mime_normalization_and_flag_prevent_download():
    remote = RemoteFile("id", "base.csv", "text/plain", "", None)
    client = FakeGoogleDriveClient([remote], {"id": b"Nome;Valor\nAcme;15"})
    cipher, _ = encrypted_credentials()
    credentials = fresh_credentials(cipher)
    provider = GoogleDriveDocumentProvider(client, cipher)
    provider.eligible_mime_types = BASE_MIME_TYPES
    assert provider._extract(encrypted_credentials=credentials, remote_file=remote).text is None
    assert not client.read_calls
    provider.eligible_mime_types = ELIGIBLE_MIME_TYPES
    result = provider._extract(encrypted_credentials=credentials, remote_file=remote)
    assert result.mime_type == "text/csv"
    assert result.blocks[0].text == "Nome: Acme | Valor: 15"


def test_onedrive_txt_is_sanitized_and_generic_mime_normalized():
    class Client:
        def _external_id(self, item):
            return item["id"]

        def _parent_ids(self, parent):
            return ()

        def read_file(self, **kwargs):
            return b"a\x00b"

    provider = OneDriveDocumentProvider(Client(), SimpleNamespace())
    provider.eligible_mime_types = ELIGIBLE_MIME_TYPES
    result = provider._read_one(
        OneDriveCredentials("token", "refresh", datetime.now(UTC)),
        {"id": "id", "name": "notes.txt", "file": {"mimeType": "application/octet-stream"}},
    )
    assert result.mime_type == "text/plain"
    assert result.text == "ab"


def test_google_propagates_encrypted_pdf_code():
    from io import BytesIO

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("password")
    out = BytesIO()
    writer.write(out)
    remote = RemoteFile("pdf", "protected.pdf", "application/pdf", "", None)
    client = FakeGoogleDriveClient([remote], {"pdf": out.getvalue()})
    cipher, _ = encrypted_credentials()
    result = GoogleDriveDocumentProvider(client, cipher)._extract(
        encrypted_credentials=fresh_credentials(cipher), remote_file=remote
    )
    assert result.error_code == "file_encrypted"


def test_google_export_size_limit_maps_to_file_too_large_code():
    from app.ingestion.google_drive import GoogleDriveDocumentProvider
    from app.integrations.google_drive import GoogleItemTooLarge

    assert issubclass(GoogleItemTooLarge, Exception)

    class Client(FakeGoogleDriveClient):
        def read_file(self, *, credentials, remote_file):
            raise GoogleItemTooLarge("exportSizeLimitExceeded")

    remote = RemoteFile("id", "big", "application/vnd.google-apps.document", "", None)
    cipher, _ = encrypted_credentials()
    found = GoogleDriveDocumentProvider(Client([remote], {}), cipher).discover(
        encrypted_credentials=fresh_credentials(cipher), selections=[selection("all_accessible")]
    )
    assert [d.error_code for d in found.documents] == ["file_too_large"]


def test_file_too_large_is_retried_by_the_next_sync_when_the_limit_changes():
    from app.ingestion.tasks import TERMINAL_ERROR_CODES

    assert "file_too_large" not in TERMINAL_ERROR_CODES
