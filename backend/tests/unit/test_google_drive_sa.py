"""M58 service-account security and credential contract (no network)."""

import json
from datetime import UTC, datetime

import httpx
import jwt
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.integrations.errors import SourceItemUnavailable
from app.integrations.google_drive import ITEM_FORBIDDEN_REASONS, GoogleCredentials
from app.integrations.google_drive_sa import (
    FolderAccessLost,
    RobotUnavailable,
    SaDriveClient,
    ServiceAccountKeyCipher,
    ServiceAccountTokenSource,
    parse_folder_id,
    raise_for_sa,
)


def response(status, data):
    return httpx.Response(status, json=data, request=httpx.Request("GET", "https://example.test"))


@pytest.mark.parametrize(
    "value",
    [
        "Abc_123456789",
        "https://drive.google.com/drive/folders/Abc_123456789?usp=sharing",
        "https://drive.google.com/drive/u/2/folders/Abc_123456789",
        "https://drive.google.com/open?id=Abc_123456789",
        "https://drive.google.com/folderview?id=Abc_123456789",
    ],
)
def test_parser_accepts_folder_variants(value):
    assert parse_folder_id(value) == "Abc_123456789"


@pytest.mark.parametrize(
    "value",
    [
        "x' or 1=1",
        "short",
        "https://drive.google.com.evil.test/drive/folders/Abc_123456789",
        "javascript:alert(1)",
        "https://drive.google.com/file/d/Abc_123456789",
        "https://docs.google.com/document/d/Abc_123456789",
        "https://drive.google.com/drive/my-drive",
    ],
)
def test_parser_rejects_unsafe_ids(value):
    with pytest.raises(ValueError):
        parse_folder_id(value)


@pytest.mark.parametrize(
    "status,reason,root,expected",
    [
        (404, "notFound", True, FolderAccessLost),
        (403, "insufficientFilePermissions", True, FolderAccessLost),
        (401, None, True, RobotUnavailable),
        (403, "cannotExportFile", False, SourceItemUnavailable),
        (403, "unknown", False, RobotUnavailable),
    ],
)
def test_sa_error_classification(status, reason, root, expected):
    with pytest.raises(expected):
        raise_for_sa(response(status, {"error": {"errors": [{"reason": reason}]}}), root=root)


def test_cannot_export_is_item_forbidden():
    assert "cannotExportFile" in ITEM_FORBIDDEN_REASONS


def test_token_signed_skew_and_cached_and_missing_access_token():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    key = {"client_email": "robot@example.test", "private_key": pem, "private_key_id": "kid"}
    cipher = ServiceAccountKeyCipher(Fernet.generate_key().decode())
    encrypted = cipher.encrypt(key)
    calls = []

    class Http:
        def request(self, method, url, **kwargs):
            calls.append(kwargs["data"])
            return response(200, {"access_token": "valid", "expires_in": 3599})

    source = ServiceAccountTokenSource(encrypted, cipher, http=Http(), clock=lambda: 100000)
    assert source.credentials().access_token == source.credentials().access_token == "valid"
    assert len(calls) == 1
    claims = jwt.decode(
        calls[0]["assertion"],
        private.public_key(),
        algorithms=["RS256"],
        options={"verify_exp": False, "verify_aud": False},
    )
    assert claims["iat"] == 99970
    assert claims["exp"] - claims["iat"] <= 3600
    assert claims["scope"] == "https://www.googleapis.com/auth/drive.readonly"
    assert "sub" not in claims
    assert "private_key" not in encrypted

    class Missing:
        def request(self, *args, **kwargs):
            return response(200, {"expires_in": 3600})

    with pytest.raises(RobotUnavailable):
        ServiceAccountTokenSource(encrypted, cipher, http=Missing()).credentials()


def test_verify_get_only_public_parent_and_shortcut():
    calls = []

    class Http:
        def request(self, method, url, **kwargs):
            calls.append((url, kwargs))
            item = {
                "id": "child_123456",
                "name": "child",
                "mimeType": "application/vnd.google-apps.folder",
                "parents": ["parent_123456"],
            }
            if url.endswith("parent_123456"):
                item.update(id="parent_123456", sharedWithMeTime="2026-10-14T00:00:00Z", parents=[])
            return response(200, item)

    client = SaDriveClient(http=Http())
    _root, share = client.verify_folder(
        credentials=GoogleCredentials("token", None, None), folder_id="child_123456"
    )
    assert share["id"] == "parent_123456"
    assert len(calls) == 2
    assert all("permissions" not in json.dumps(kwargs.get("params")) for _, kwargs in calls)
    assert all("/files/" in url for url, _ in calls)

    class Public:
        def request(self, *args, **kwargs):
            return response(
                200, {"id": "public_123456", "mimeType": "application/vnd.google-apps.folder"}
            )

    with pytest.raises(FolderAccessLost):
        SaDriveClient(http=Public()).verify_folder(
            credentials=GoogleCredentials("t", None, None), folder_id="public_123456"
        )


def test_native_export_size_falls_back_to_plain_text():
    from app.integrations.google_drive import RemoteFile

    calls = []

    class Http:
        def request(self, method, url, **kwargs):
            calls.append(kwargs["params"]["mimeType"])
            if calls[-1] != "text/plain":
                return response(403, {"error": {"errors": [{"reason": "exportSizeLimitExceeded"}]}})
            return httpx.Response(200, content=b"plain", request=httpx.Request("GET", url))

    client = SaDriveClient(http=Http())
    file = RemoteFile(
        "native_123456", "slides", "application/vnd.google-apps.presentation", "url", None
    )
    with client.read_file(
        credentials=GoogleCredentials("t", None, None), remote_file=file
    ) as content:
        assert content.read() == b"plain"
        assert content.extraction_mime_type == "text/plain"
    assert calls == [
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "text/plain",
    ]


def test_removed_root_batch_aborts_before_pruning():
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ingestion.google_drive import GoogleDriveDocumentProvider
    from app.integrations.google_drive import CredentialCipher, GoogleChangesPage, RemoteFolder
    from app.workspaces.models import WorkspaceFolderSelection

    cipher = CredentialCipher(Fernet.generate_key().decode())

    class Client:
        def list_folders(self, **kw):
            return [RemoteFolder("root_123456", "root")]

        def changes(self, **kw):
            return GoogleChangesPage(
                [
                    {"fileId": "root_123456", "removed": True},
                    {"fileId": "file_123456", "removed": True},
                ],
                "next",
            )

    provider = GoogleDriveDocumentProvider(
        Client(),
        cipher,
        credential_source=SimpleNamespace(credentials=lambda: GoogleCredentials("t", None, None)),
    )
    selection = WorkspaceFolderSelection(
        id=uuid4(),
        workspace_folder_id=uuid4(),
        kind="folder",
        external_folder_id="root_123456",
        encrypted_delta_link=cipher.encrypt_cursor("cursor"),
    )
    with pytest.raises(FolderAccessLost):
        provider.discover(encrypted_credentials="", selections=[selection])


def test_disabled_registry_has_no_robot_provider():
    from app.core.config import Settings
    from app.integrations.base import ProviderNotConfigured
    from app.integrations.registry import IntegrationRegistry

    settings = Settings(database_url="postgresql+psycopg://u:p@localhost/db", _env_file=None)
    with pytest.raises(ProviderNotConfigured):
        IntegrationRegistry(settings).get("google_drive_sa")


def test_legacy_domain_folder_link():
    assert (
        parse_folder_id("https://drive.google.com/a/acme.com.br/drive/folders/Abc_123456789")
        == "Abc_123456789"
    )


@pytest.mark.parametrize("age,expected", [(0, False), (2, True)])
def test_daily_full_reconciliation_without_modified_time(age, expected):
    from datetime import timedelta
    from types import SimpleNamespace
    from uuid import uuid4

    from app.ingestion.service import DiscoveryResult
    from app.integrations.registry import GoogleDriveSaProviderAdapter
    from app.workspaces.models import WorkspaceFolderSelection

    adapter = GoogleDriveSaProviderAdapter.__new__(GoogleDriveSaProviderAdapter)
    calls = []

    class Provider:
        credential_source = SimpleNamespace(credentials=lambda: GoogleCredentials("t", None, None))

        def discover(self, **kwargs):
            calls.append(kwargs)
            return DiscoveryResult(documents=[], full_snapshot=kwargs.get("force_full", False))

    link = SimpleNamespace(
        external_folder_id="root_123456",
        status="verified",
        last_reconciled_at=datetime.now(UTC) - timedelta(days=age),
    )
    adapter._provider = Provider()
    adapter.source = SimpleNamespace()
    adapter.service = SimpleNamespace(
        links=lambda source: [link], client=SimpleNamespace(verify_folder=lambda **kw: None)
    )
    result = adapter.discover(
        encrypted_credentials="",
        selections=[
            WorkspaceFolderSelection(id=uuid4(), kind="folder", external_folder_id="root_123456")
        ],
    )
    assert result.full_snapshot is expected
    assert "modifiedTime" not in str(calls)


def test_invalid_robot_private_key_is_ops_error():
    cipher = ServiceAccountKeyCipher(Fernet.generate_key().decode())
    encrypted = cipher.encrypt(
        {"client_email": "robot@example.test", "private_key": "invalid", "private_key_id": "id"}
    )
    with pytest.raises(RobotUnavailable):
        ServiceAccountTokenSource(encrypted, cipher).credentials()


def test_blocked_download_is_marked_without_fetching():
    from types import SimpleNamespace

    from app.ingestion.google_drive import GoogleDriveDocumentProvider
    from app.integrations.google_drive import CredentialCipher, RemoteFile

    class Client:
        def read_file(self, **kw):
            pytest.fail("blocked file must not be downloaded")

    provider = GoogleDriveDocumentProvider(
        Client(),
        CredentialCipher(Fernet.generate_key().decode()),
        credential_source=SimpleNamespace(credentials=lambda: GoogleCredentials("t", None, None)),
    )
    result = provider._extract(
        encrypted_credentials="",
        remote_file=RemoteFile(
            "file_123456", "file.txt", "text/plain", "url", None, can_download=False
        ),
    )
    assert result.error_code == "source_file_unavailable"


def test_shortcut_targets_are_never_followed():
    client = SaDriveClient()
    calls = []
    root = {
        "id": "root_123456",
        "name": "root",
        "mimeType": "application/vnd.google-apps.folder",
        "sharedWithMeTime": "2026-10-14T00:00:00Z",
    }

    def metadata(**kw):
        calls.append(kw["file_id"])
        return root

    client.metadata = metadata
    client._list = lambda *args: [
        {
            "id": "shortcut_123456",
            "name": "external",
            "mimeType": "application/vnd.google-apps.shortcut",
            "shortcutDetails": {"targetId": "outside_123456"},
        }
    ]
    assert (
        client.list_folder_files(
            credentials=GoogleCredentials("t", None, None), root_folder_id="root_123456"
        )
        == []
    )
    assert "outside_123456" not in calls
