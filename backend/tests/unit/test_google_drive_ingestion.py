from datetime import UTC, datetime, timedelta
from io import BytesIO
from threading import Event, Lock, Thread
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from docx import Document as DocxDocument

from app.ingestion.google_drive import GoogleDriveDocumentProvider
from app.integrations.google_drive import (
    CredentialCipher,
    GoogleChangesPage,
    GoogleCredentials,
    GoogleCursorInvalid,
    GoogleDriveOAuthClient,
    GoogleRefreshTokenInvalid,
    GoogleRemoteUnauthorized,
    RemoteFile,
    RemoteFolder,
)
from app.workspaces.models import WorkspaceFolderSelection

GOOGLE_DOC = "application/vnd.google-apps.document"
PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class FakeGoogleDriveClient:
    def __init__(self, files: list[RemoteFile], content: dict[str, bytes], root_files: list[RemoteFile] | None = None, all_files: list[RemoteFile] | None = None) -> None:
        self.files = files
        self.content = content
        self.root_files = root_files if root_files is not None else files
        self.all_files = all_files if all_files is not None else files
        self.list_calls: list[str] = []
        self.read_calls: list[str] = []
        self.read_error: Exception | None = None
        self.refresh_calls: list[str] = []

    def refresh_access_token(self, *, refresh_token: str) -> GoogleCredentials:
        self.refresh_calls.append(refresh_token)
        return GoogleCredentials(
            "refreshed-access-token",
            refresh_token,
            datetime.now(UTC) + timedelta(hours=1),
        )

    def start_page_token(self, *, credentials: GoogleCredentials) -> str:
        return "initial-cursor"

    def list_folder_files(self, *, credentials: GoogleCredentials, root_folder_id: str) -> list[RemoteFile]:
        self.list_calls.append(root_folder_id)
        return self.files

    def list_root_files(self, *, credentials: GoogleCredentials) -> list[RemoteFile]:
        self.list_calls.append("root")
        return self.root_files

    def list_all_files(self, *, credentials: GoogleCredentials) -> list[RemoteFile]:
        self.list_calls.append("all")
        return self.all_files

    def list_folders(self, *, credentials: GoogleCredentials) -> list[RemoteFolder]:
        return []

    def read_file(self, *, credentials: GoogleCredentials, remote_file: RemoteFile) -> bytes:
        self.read_calls.append(remote_file.id)
        if self.read_error is not None:
            raise self.read_error
        return self.content[remote_file.id]


def encrypted_credentials() -> tuple[CredentialCipher, str]:
    cipher = CredentialCipher(Fernet.generate_key().decode())
    return cipher, cipher.encrypt(GoogleCredentials("access-token", "refresh-token", None))


def expiring_credentials(cipher: CredentialCipher) -> str:
    return cipher.encrypt(
        GoogleCredentials(
            "access-token",
            "refresh-token",
            datetime.now(UTC) + timedelta(minutes=1),
        )
    )


def fresh_credentials(cipher: CredentialCipher) -> str:
    return cipher.encrypt(
        GoogleCredentials(
            "access-token",
            "refresh-token",
            datetime.now(UTC) + timedelta(hours=1),
        )
    )


def remote_file(file_id: str, mime_type: str) -> RemoteFile:
    return RemoteFile(
        id=file_id,
        name=f"{file_id}.document",
        mime_type=mime_type,
        source_url=f"https://drive.example.test/{file_id}",
        modified_at=None,
    )


def selection(kind: str, external_folder_id: str = "") -> WorkspaceFolderSelection:
    return WorkspaceFolderSelection(id=uuid4(), workspace_folder_id=uuid4(), kind=kind, external_folder_id=external_folder_id)


def docx_bytes(text: str) -> bytes:
    document = DocxDocument()
    document.add_paragraph(text)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def test_provider_extracts_google_docs_and_docx_and_skips_unsupported_without_download() -> None:
    files = [remote_file("google-doc", GOOGLE_DOC), remote_file("word-doc", DOCX), remote_file("slides", "application/vnd.google-apps.presentation")]
    client = FakeGoogleDriveClient(
        files,
        {
            "google-doc": b"Approved marketing scope",
            "word-doc": docx_bytes("Approved consulting scope"),
        },
    )
    cipher, _ = encrypted_credentials()
    credentials = fresh_credentials(cipher)

    discovered = GoogleDriveDocumentProvider(client, cipher).discover(
        encrypted_credentials=credentials,
        selections=[selection("folder", "root-folder")],
    )

    assert discovered.full_snapshot is True
    assert discovered.delta_links
    assert client.list_calls == ["root-folder"]
    assert set(client.read_calls) == {"google-doc", "word-doc"}
    assert [(document.external_file_id, document.text, document.error_code) for document in discovered.documents] == [
        ("google-doc", "Approved marketing scope", None),
        ("slides", None, None),
        ("word-doc", "Approved consulting scope", None),
    ]


def test_provider_proactively_refreshes_expiring_credentials_and_exposes_ciphertext() -> None:
    client = FakeGoogleDriveClient([], {})
    cipher, _ = encrypted_credentials()
    provider = GoogleDriveDocumentProvider(client, cipher)

    assert provider.folders(encrypted_credentials=expiring_credentials(cipher)) == []

    assert client.refresh_calls == ["refresh-token"]
    assert provider.updated_encrypted_credentials is not None
    refreshed = cipher.decrypt(provider.updated_encrypted_credentials)
    assert refreshed.access_token == "refreshed-access-token"
    assert refreshed.refresh_token == "refresh-token"


def test_provider_retries_a_remote_unauthorized_call_once_after_refresh() -> None:
    class Client(FakeGoogleDriveClient):
        def __init__(self) -> None:
            super().__init__([], {})
            self.folder_calls = 0

        def list_folders(self, *, credentials: GoogleCredentials) -> list[RemoteFolder]:
            self.folder_calls += 1
            if self.folder_calls == 1:
                raise GoogleRemoteUnauthorized()
            assert credentials.access_token == "refreshed-access-token"
            return []

    client = Client()
    cipher, _ = encrypted_credentials()
    credentials = fresh_credentials(cipher)

    assert GoogleDriveDocumentProvider(client, cipher).folders(encrypted_credentials=credentials) == []
    assert client.folder_calls == 2
    assert client.refresh_calls == ["refresh-token"]


def test_provider_propagates_invalid_refresh_token_after_one_attempt() -> None:
    class Client(FakeGoogleDriveClient):
        def refresh_access_token(self, *, refresh_token: str) -> GoogleCredentials:
            self.refresh_calls.append(refresh_token)
            raise GoogleRefreshTokenInvalid("revoked")

    client = Client([], {})
    cipher, credentials = encrypted_credentials()

    with pytest.raises(GoogleRemoteUnauthorized):
        GoogleDriveDocumentProvider(client, cipher).folders(encrypted_credentials=credentials)

    assert client.refresh_calls == ["refresh-token"]


def test_concurrent_provider_refreshes_persist_once_and_reuses_locked_source_credentials() -> None:
    cipher, _ = encrypted_credentials()
    source = SimpleNamespace(id=uuid4(), encrypted_credentials=expiring_credentials(cipher))
    row_lock = Lock()

    class LockedSession:
        def __init__(self) -> None:
            self.locked = False

        def scalar(self, _: object):
            row_lock.acquire()
            self.locked = True
            return source

        def commit(self) -> None:
            if self.locked:
                self.locked = False
                row_lock.release()

    class Client(FakeGoogleDriveClient):
        def __init__(self) -> None:
            super().__init__([], {})
            self.refresh_lock = Lock()

        def refresh_access_token(self, *, refresh_token: str) -> GoogleCredentials:
            with self.refresh_lock:
                self.refresh_calls.append(refresh_token)
            return GoogleCredentials(
                "shared-refreshed-access-token",
                "rotated-refresh-token",
                datetime.now(UTC) + timedelta(hours=1),
            )

    client = Client()
    stale_credentials = source.encrypted_credentials
    providers = [
        GoogleDriveDocumentProvider(client, cipher, session=LockedSession(), source_id=source.id)
        for _ in range(2)
    ]
    threads = [
        Thread(target=lambda provider=provider: provider.folders(
            encrypted_credentials=stale_credentials
        ))
        for provider in providers
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert all(not thread.is_alive() for thread in threads)
    assert client.refresh_calls == ["refresh-token"]
    persisted = cipher.decrypt(source.encrypted_credentials)
    assert persisted == GoogleCredentials(
        "shared-refreshed-access-token",
        "rotated-refresh-token",
        persisted.expires_at,
    )
    assert all(
        provider.updated_encrypted_credentials == source.encrypted_credentials
        for provider in providers
    )


def test_provider_removes_nul_from_extracted_text_and_blocks() -> None:
    client = FakeGoogleDriveClient(
        [remote_file("google-doc", GOOGLE_DOC)],
        {"google-doc": b"Before\x00 after"},
    )
    cipher, credentials = encrypted_credentials()

    discovered = GoogleDriveDocumentProvider(client, cipher).discover(
        encrypted_credentials=credentials,
        selections=[selection("folder", "root-folder")],
    )

    assert discovered.documents[0].text == "Before after"
    assert [block.text for block in discovered.documents[0].blocks] == ["Before after"]


def test_provider_retains_safe_parent_metadata_for_library_projection() -> None:
    file = RemoteFile(
        id="brief",
        name="brief.document",
        mime_type=GOOGLE_DOC,
        source_url="https://drive.example.test/brief",
        modified_at=None,
        parent_ids=("campaign",),
    )
    client = FakeGoogleDriveClient([file], {"brief": b"Approved scope"})
    cipher, credentials = encrypted_credentials()

    discovered = GoogleDriveDocumentProvider(client, cipher).discover(
        encrypted_credentials=credentials,
        selections=[selection("folder", "root-folder")],
    )

    assert discovered.documents[0].parent_ids == ("campaign",)


def test_structured_extraction_preserves_markdown_sections_and_docx_headings_tables() -> None:
    from app.ingestion.google_drive import _extract_blocks

    markdown = _extract_blocks("text/markdown", b"# Billing\n\nInvoices are due in 30 days.\n\n## Exceptions\n\nContact finance.")
    assert [block.section_path for block in markdown] == ["Billing", "Billing › Exceptions"]
    assert "Invoices are due" in markdown[0].text

    docx = DocxDocument()
    docx.add_heading("Policy", level=1)
    docx.add_paragraph("Employees submit expenses monthly.")
    table = docx.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Category"
    table.cell(0, 1).text = "Limit"
    table.cell(1, 0).text = "Travel"
    table.cell(1, 1).text = "$500"
    output = BytesIO()
    docx.save(output)
    docx_blocks = _extract_blocks(DOCX, output.getvalue())
    assert docx_blocks[0].section_path == "Policy"
    assert docx_blocks[1].section_path == "Policy"
    assert "Category: Travel" in docx_blocks[1].text and "Limit: $500" in docx_blocks[1].text


def test_provider_extracts_pdf_text(monkeypatch: pytest.MonkeyPatch) -> None:
    class Page:
        def extract_text(self) -> str:
            return "PDF source evidence"

    class FakePdfReader:
        def __init__(self) -> None:
            self.pages = [Page()]
            self.is_encrypted = False

    monkeypatch.setattr("app.ingestion.extraction.pdf.PdfReader", lambda _: FakePdfReader())
    client = FakeGoogleDriveClient([remote_file("report", PDF)], {"report": b"not-real-pdf"})
    cipher, credentials = encrypted_credentials()

    discovered = GoogleDriveDocumentProvider(client, cipher).discover(
        encrypted_credentials=credentials,
        selections=[selection("folder", "root-folder")],
    )

    assert discovered.documents[0].text == "PDF source evidence"
    assert discovered.documents[0].error_code is None


def test_remote_file_authorization_error_becomes_a_document_failure() -> None:
    client = FakeGoogleDriveClient([remote_file("private-doc", GOOGLE_DOC)], {"private-doc": b"irrelevant"})
    client.read_error = GoogleRemoteUnauthorized()
    cipher, credentials = encrypted_credentials()

    discovered = GoogleDriveDocumentProvider(client, cipher).discover(
        encrypted_credentials=credentials,
        selections=[selection("folder", "root-folder")],
    )

    assert discovered.documents[0].error_code == "source_file_unavailable"


def test_provider_unions_overlapping_folder_selections_before_downloading() -> None:
    item = remote_file("shared-doc", GOOGLE_DOC)
    client = FakeGoogleDriveClient([item], {"shared-doc": b"Only once"})
    cipher, credentials = encrypted_credentials()

    discovered = GoogleDriveDocumentProvider(client, cipher).discover(
        encrypted_credentials=credentials,
        selections=[selection("folder", "parent"), selection("folder", "child")],
    )

    assert client.list_calls == ["parent", "child"]
    assert client.read_calls == ["shared-doc"]
    assert [item.external_file_id for item in discovered.documents] == ["shared-doc"]


def test_provider_combines_direct_root_files_without_traversing_root_folders() -> None:
    folder_file = remote_file("folder-doc", GOOGLE_DOC)
    root_file = remote_file("root-doc", GOOGLE_DOC)
    client = FakeGoogleDriveClient(
        [folder_file],
        {"folder-doc": b"In selected folder", "root-doc": b"At root"},
        root_files=[root_file],
    )
    cipher, credentials = encrypted_credentials()

    discovered = GoogleDriveDocumentProvider(client, cipher).discover(
        encrypted_credentials=credentials,
        selections=[selection("folder", "project"), selection("root_files")],
    )

    assert client.list_calls == ["project", "root"]
    assert {item.external_file_id for item in discovered.documents} == {"folder-doc", "root-doc"}


def test_provider_all_accessible_uses_one_complete_listing() -> None:
    item = remote_file("anywhere", GOOGLE_DOC)
    client = FakeGoogleDriveClient([], {"anywhere": b"Accessible"}, all_files=[item])
    cipher, credentials = encrypted_credentials()

    discovered = GoogleDriveDocumentProvider(client, cipher).discover(
        encrypted_credentials=credentials,
        selections=[selection("all_accessible")],
    )

    assert client.list_calls == ["all"]
    assert [item.external_file_id for item in discovered.documents] == ["anywhere"]


def test_provider_extracts_with_bounded_concurrency_and_stable_order() -> None:
    files = [remote_file(f"file-{index}", GOOGLE_DOC) for index in reversed(range(7))]

    class BlockingClient(FakeGoogleDriveClient):
        def __init__(self) -> None:
            super().__init__(files, {item.id: item.id.encode() for item in files})
            self.lock = Lock()
            self.active_reads = 0
            self.max_active_reads = 0
            self.three_reads_started = Event()
            self.release_reads = Event()

        def read_file(self, *, credentials: GoogleCredentials, remote_file: RemoteFile) -> bytes:
            with self.lock:
                self.active_reads += 1
                self.max_active_reads = max(self.max_active_reads, self.active_reads)
                if self.active_reads == 3:
                    self.three_reads_started.set()
            self.release_reads.wait(timeout=2)
            try:
                return super().read_file(credentials=credentials, remote_file=remote_file)
            finally:
                with self.lock:
                    self.active_reads -= 1

    client = BlockingClient()
    cipher, credentials = encrypted_credentials()
    discovered = []
    thread = Thread(
        target=lambda: discovered.extend(
            GoogleDriveDocumentProvider(client, cipher, extraction_workers=100).discover(
                encrypted_credentials=credentials,
                selections=[selection("all_accessible")],
            ).documents
        )
    )

    thread.start()
    assert client.three_reads_started.wait(timeout=2)
    client.release_reads.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert client.max_active_reads == 3
    assert [item.external_file_id for item in discovered] == sorted(item.id for item in files)
    assert [item.text for item in discovered] == sorted(item.id for item in files)


def test_concurrent_extraction_keeps_per_file_failures_without_cancelling_siblings() -> None:
    files = [
        remote_file("good-a", GOOGLE_DOC),
        remote_file("private", GOOGLE_DOC),
        remote_file("bad", GOOGLE_DOC),
        remote_file("slides", "application/vnd.google-apps.presentation"),
        remote_file("good-b", GOOGLE_DOC),
    ]

    class SelectivelyFailingClient(FakeGoogleDriveClient):
        def read_file(self, *, credentials: GoogleCredentials, remote_file: RemoteFile) -> bytes:
            if remote_file.id == "private":
                raise GoogleRemoteUnauthorized()
            if remote_file.id == "bad":
                raise ValueError("invalid source")
            return super().read_file(credentials=credentials, remote_file=remote_file)

    client = SelectivelyFailingClient(
        files,
        {"good-a": b"Good A", "good-b": b"Good B", "private": b"", "bad": b""},
    )
    cipher, credentials = encrypted_credentials()

    discovered = GoogleDriveDocumentProvider(client, cipher, extraction_workers=2).discover(
        encrypted_credentials=credentials,
        selections=[selection("all_accessible")],
    )

    assert [(item.external_file_id, item.text, item.error_code) for item in discovered.documents] == [
        ("bad", None, "text_extraction_failed"),
        ("good-a", "Good A", None),
        ("good-b", "Good B", None),
        ("private", None, "source_file_unavailable"),
        ("slides", None, None),
    ]
    assert "slides" not in client.read_calls


def test_google_client_lists_direct_root_files_with_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    class Response:
        status_code = 200

        def __init__(self, body: dict[str, object]) -> None:
            self.body = body

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return self.body

    pages = [
        {"nextPageToken": "next", "files": [{"id": "root-a", "name": "A", "mimeType": GOOGLE_DOC}]},
        {"files": [{"id": "root-b", "name": "B", "mimeType": PDF}]},
    ]

    def fake_get(_: str, *, params: dict[str, object], **__: object) -> Response:
        calls.append(params)
        return Response(pages.pop(0))

    monkeypatch.setattr("app.integrations.google_drive.httpx.get", fake_get)
    files = GoogleDriveOAuthClient(client_id="id", client_secret="secret", redirect_uri="https://example.test/callback").list_root_files(
        credentials=GoogleCredentials("access", None, None)
    )

    assert [item.id for item in files] == ["root-a", "root-b"]
    assert calls[0]["q"] == "'root' in parents and trashed = false and mimeType != 'application/vnd.google-apps.folder'"
    assert calls[0]["pageToken"] is None
    assert calls[1]["pageToken"] == "next"
    assert calls[0]["supportsAllDrives"] == "true"


def test_google_incremental_downloads_only_changed_file_in_selected_root() -> None:
    unchanged = remote_file("unchanged", GOOGLE_DOC)
    changed = remote_file("changed", GOOGLE_DOC)

    class Client(FakeGoogleDriveClient):
        def changes(self, *, credentials: GoogleCredentials, page_token: str) -> GoogleChangesPage:
            assert page_token == "previous"
            return GoogleChangesPage(
                changes=[{"fileId": "changed", "file": {
                    "id": "changed", "name": "changed.document", "mimeType": GOOGLE_DOC,
                    "parents": ["actual-root-id"],
                }}],
                new_start_page_token="next",
            )

        _remote_file = staticmethod(GoogleDriveOAuthClient._remote_file)

    client = Client([unchanged, changed], {"changed": b"Changed text"})
    cipher, credentials = encrypted_credentials()
    scope = selection("root_files")
    scope.encrypted_delta_link = cipher.encrypt_cursor("previous")

    result = GoogleDriveDocumentProvider(client, cipher).discover(
        encrypted_credentials=credentials, selections=[scope]
    )

    assert result.full_snapshot is False
    assert [document.external_file_id for document in result.documents] == ["changed"]
    assert client.read_calls == ["changed"]
    assert result.delta_links == {scope.id: "next"}


def test_incremental_sync_reuses_folder_catalog_for_library_projection() -> None:
    class Client(FakeGoogleDriveClient):
        folder_calls = 0

        def list_folders(self, *, credentials: GoogleCredentials) -> list:
            self.folder_calls += 1
            return []

        def changes(self, *, credentials: GoogleCredentials, page_token: str) -> GoogleChangesPage:
            return GoogleChangesPage(changes=[], new_start_page_token="next")

    client = Client([], {})
    cipher, credentials = encrypted_credentials()
    scope = selection("folder", "selected-folder")
    scope.encrypted_delta_link = cipher.encrypt_cursor("previous")
    provider = GoogleDriveDocumentProvider(client, cipher)

    provider.discover(encrypted_credentials=credentials, selections=[scope])
    assert provider.folders(encrypted_credentials=credentials) == []
    assert client.folder_calls == 1


@pytest.mark.parametrize("change_kind", ["folder_changed", "cursor_invalid"])
def test_full_reconciliation_refreshes_folder_catalog(change_kind: str) -> None:
    class Client(FakeGoogleDriveClient):
        folder_calls = 0

        def list_folders(self, *, credentials: GoogleCredentials) -> list[RemoteFolder]:
            self.folder_calls += 1
            name = "Before" if self.folder_calls == 1 else "After"
            return [RemoteFolder(id="selected-folder", name=name)]

        def changes(self, *, credentials: GoogleCredentials, page_token: str) -> GoogleChangesPage:
            if change_kind == "cursor_invalid":
                raise GoogleCursorInvalid("expired")
            return GoogleChangesPage(
                changes=[{"fileId": "selected-folder", "file": {
                    "id": "selected-folder", "name": "After",
                    "mimeType": "application/vnd.google-apps.folder",
                }}],
                new_start_page_token="next",
            )

        _remote_file = staticmethod(GoogleDriveOAuthClient._remote_file)

    client = Client([], {})
    cipher, credentials = encrypted_credentials()
    scope = selection("folder", "selected-folder")
    scope.encrypted_delta_link = cipher.encrypt_cursor("previous")
    provider = GoogleDriveDocumentProvider(client, cipher)

    result = provider.discover(encrypted_credentials=credentials, selections=[scope])

    assert result.full_snapshot is True
    assert [folder.name for folder in provider.folders(encrypted_credentials=credentials)] == ["After"]
    assert client.folder_calls == 2


def test_google_removed_item_reconciles_full_scope_for_deleted_subtrees() -> None:
    retained = remote_file("retained", GOOGLE_DOC)

    class Client(FakeGoogleDriveClient):
        def changes(self, *, credentials: GoogleCredentials, page_token: str) -> GoogleChangesPage:
            return GoogleChangesPage(
                changes=[{"fileId": "removed-folder", "removed": True}],
                new_start_page_token="next",
            )

        def list_folders(self, *, credentials: GoogleCredentials) -> list:
            return []

    client = Client([retained], {"retained": b"Retained text"})
    cipher, credentials = encrypted_credentials()
    scope = selection("folder", "selected-folder")
    scope.encrypted_delta_link = cipher.encrypt_cursor("previous")

    result = GoogleDriveDocumentProvider(client, cipher).discover(
        encrypted_credentials=credentials, selections=[scope]
    )

    assert result.full_snapshot is True
    assert [document.external_file_id for document in result.documents] == ["retained"]
    assert client.list_calls == ["selected-folder"]


def test_google_manual_reprocess_forces_remote_read_without_delta_change() -> None:
    item = remote_file("manual", GOOGLE_DOC)

    class Client(FakeGoogleDriveClient):
        def changes(self, *, credentials: GoogleCredentials, page_token: str) -> GoogleChangesPage:
            return GoogleChangesPage(changes=[], new_start_page_token="next")

        def get_file(self, *, credentials: GoogleCredentials, file_id: str) -> RemoteFile | None:
            assert file_id == "manual"
            return item

    client = Client([item], {"manual": b"Reprocessed text"})
    cipher, credentials = encrypted_credentials()
    scope = selection("all_accessible")
    scope.encrypted_delta_link = cipher.encrypt_cursor("previous")

    result = GoogleDriveDocumentProvider(client, cipher).discover(
        encrypted_credentials=credentials,
        selections=[scope],
        force_file_ids={"manual"},
    )

    assert [document.external_file_id for document in result.documents] == ["manual"]
    assert client.read_calls == ["manual"]


def test_google_expired_cursor_falls_back_to_snapshot_and_replaces_cursor() -> None:
    item = remote_file("snapshot-item", GOOGLE_DOC)

    class Client(FakeGoogleDriveClient):
        def changes(self, *, credentials: GoogleCredentials, page_token: str) -> GoogleChangesPage:
            raise GoogleCursorInvalid("expired")

        def list_folders(self, *, credentials: GoogleCredentials) -> list:
            return []

    client = Client([item], {"snapshot-item": b"Snapshot text"})
    cipher, credentials = encrypted_credentials()
    scope = selection("folder", "selected-folder")
    scope.encrypted_delta_link = cipher.encrypt_cursor("expired")

    result = GoogleDriveDocumentProvider(client, cipher).discover(
        encrypted_credentials=credentials, selections=[scope]
    )

    assert result.full_snapshot is True
    assert result.delta_links == {scope.id: "initial-cursor"}
    assert [document.external_file_id for document in result.documents] == ["snapshot-item"]


def test_google_manual_reprocess_forces_remote_read_without_delta_change_full_snapshot() -> None:
    item = remote_file("manual", GOOGLE_DOC)

    class Client(FakeGoogleDriveClient):
        def changes(self, *, credentials: GoogleCredentials, page_token: str) -> GoogleChangesPage:
            return GoogleChangesPage(changes=[], new_start_page_token="next")

        def get_file(self, *, credentials: GoogleCredentials, file_id: str) -> RemoteFile | None:
            assert file_id == "manual"
            return item

    client = Client([item], {"manual": b"Reprocessed text"})
    cipher, credentials = encrypted_credentials()
    scope = selection("all_accessible")
    scope.encrypted_delta_link = cipher.encrypt_cursor("previous")

    result = GoogleDriveDocumentProvider(client, cipher).discover(
        encrypted_credentials=credentials,
        selections=[scope],
        force_full=True,
    )

    assert [document.external_file_id for document in result.documents] == ["manual"]
    assert client.read_calls == ["manual"]


def test_item_level_403_fails_the_document_without_refreshing_or_reauth() -> None:
    from app.integrations.google_drive import GoogleItemUnavailable

    client = FakeGoogleDriveClient([remote_file("locked", PDF)], {"locked": b""})
    client.read_error = GoogleItemUnavailable("insufficientFilePermissions")
    cipher, _ = encrypted_credentials()
    credentials = fresh_credentials(cipher)

    discovered = GoogleDriveDocumentProvider(client, cipher).discover(
        encrypted_credentials=credentials, selections=[selection("folder", "root")]
    )

    assert discovered.documents[0].error_code == "source_file_unavailable"
    assert client.refresh_calls == []


def test_oversized_drive_file_is_rejected_from_its_size_field_without_download() -> None:
    from app.ingestion.extraction import limits

    big = RemoteFile(id="big", name="big.pdf", mime_type=PDF, source_url="u", modified_at=None,
                     size=limits.MAX_FILE_BYTES + 1)
    client = FakeGoogleDriveClient([big], {"big": b"%PDF"})
    cipher, _ = encrypted_credentials()
    discovered = GoogleDriveDocumentProvider(client, cipher).discover(
        encrypted_credentials=fresh_credentials(cipher), selections=[selection("folder", "root-folder")]
    )
    assert [d.error_code for d in discovered.documents] == ["file_too_large"]
    assert client.read_calls == []


def test_drive_extraction_uses_three_workers() -> None:
    from app.ingestion import google_drive

    assert google_drive.MAX_EXTRACTION_WORKERS == 3


def test_max_file_bytes_is_one_env_shared_by_sharepoint(monkeypatch) -> None:
    from app.core.config import Settings
    from app.ingestion.extraction import limits

    assert limits.MAX_FILE_BYTES == 100 * 1024 * 1024
    monkeypatch.setenv("MAX_FILE_BYTES", "1000")
    assert limits.env_int("MAX_FILE_BYTES", 1) == 1000
    assert Settings(database_url="postgresql+psycopg://u:p@localhost:5432/db").max_file_bytes == 1000
