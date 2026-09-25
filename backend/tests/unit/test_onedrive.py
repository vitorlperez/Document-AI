from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet

from app.integrations.onedrive import (
    GRAPH_ROOT,
    GRAPH_SCOPES,
    MICROSOFT_AUTHORITY,
    DeltaPage,
    MicrosoftGraphClient,
    OneDriveCipher,
    OneDriveCredentials,
    OneDriveDeltaExpired,
    OneDriveDocumentProvider,
    OneDriveOAuthInvalid,
    OneDriveOAuthUnavailable,
)


def _http_response(
    url: str, payload: dict[str, object], *, status_code: int = 200
) -> httpx.Response:
    return httpx.Response(status_code, json=payload, request=httpx.Request("GET", url))


def test_microsoft_authorization_url_scopes_state_and_personal_or_work_accounts() -> None:
    client = MicrosoftGraphClient(
        client_id="microsoft-client",
        client_secret="microsoft-secret",
        redirect_uri="https://app.example.test/data-sources/onedrive/oauth/callback",
    )

    url = client.authorization_url(state="one-time-state")
    query = httpx.URL(url).params

    assert url.startswith(f"{MICROSOFT_AUTHORITY}/authorize?")
    assert httpx.URL(url).path == "/common/oauth2/v2.0/authorize"
    assert query["client_id"] == "microsoft-client"
    assert query["response_type"] == "code"
    assert query["redirect_uri"] == "https://app.example.test/data-sources/onedrive/oauth/callback"
    assert query["response_mode"] == "query"
    assert query["prompt"] == "select_account"
    assert query["scope"] == GRAPH_SCOPES
    assert query["state"] == "one-time-state"


def test_microsoft_refresh_uses_common_token_endpoint_and_keeps_refresh_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MicrosoftGraphClient(
        client_id="microsoft-client",
        client_secret="microsoft-secret",
        redirect_uri="https://app.example.test/data-sources/onedrive/oauth/callback",
    )
    previous = OneDriveCredentials(
        "old-access", "existing-refresh", datetime.now(UTC) + timedelta(hours=1)
    )
    calls: list[tuple[str, dict[str, str | None]]] = []

    def post(url: str, *, data: dict[str, str | None], timeout: int) -> httpx.Response:
        calls.append((url, data))
        assert timeout == 15
        return httpx.Response(
            200,
            json={"access_token": "new-access", "expires_in": 1800},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr("app.integrations.onedrive.httpx.post", post)

    refreshed = client.refresh(credentials=previous)

    assert calls == [
        (
            "https://login.microsoftonline.com/common/oauth2/v2.0/token",
            {
                "grant_type": "refresh_token",
                "refresh_token": "existing-refresh",
                "scope": GRAPH_SCOPES,
                "client_id": "microsoft-client",
                "client_secret": "microsoft-secret",
            },
        )
    ]
    assert refreshed.access_token == "new-access"
    assert refreshed.refresh_token == "existing-refresh"
    assert refreshed.expires_at > datetime.now(UTC)


def test_onedrive_cipher_encrypts_credentials_and_delta_cursors() -> None:
    cipher = OneDriveCipher(Fernet.generate_key().decode())
    credentials = OneDriveCredentials(
        "access-secret", "refresh-secret", datetime.now(UTC) + timedelta(hours=1)
    )

    encrypted_credentials = cipher.encrypt_credentials(credentials)
    encrypted_cursor = cipher.encrypt_cursor("https://graph.microsoft.com/v1.0/delta?token=cursor")

    assert encrypted_credentials != credentials.access_token
    assert credentials.access_token not in encrypted_credentials
    assert credentials.refresh_token not in encrypted_credentials
    assert cipher.decrypt_credentials(encrypted_credentials) == credentials
    assert encrypted_cursor != "https://graph.microsoft.com/v1.0/delta?token=cursor"
    assert (
        cipher.decrypt_cursor(encrypted_cursor)
        == "https://graph.microsoft.com/v1.0/delta?token=cursor"
    )


def test_onedrive_cipher_rejects_tampered_credentials_and_cursors() -> None:
    cipher = OneDriveCipher(Fernet.generate_key().decode())

    with pytest.raises(OneDriveOAuthInvalid):
        cipher.decrypt_credentials("not-encrypted")
    with pytest.raises(OneDriveOAuthInvalid):
        cipher.decrypt_cursor("not-encrypted")
    with pytest.raises(OneDriveOAuthUnavailable):
        OneDriveCipher(None).encrypt_cursor("cursor")


def test_graph_pagination_collects_all_pages_and_rejects_untrusted_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MicrosoftGraphClient(
        client_id="id", client_secret="secret", redirect_uri="https://callback"
    )
    credentials = OneDriveCredentials("access", "refresh", datetime.now(UTC) + timedelta(hours=1))
    first_url = f"{GRAPH_ROOT}/me/drive/root/children"
    next_url = f"{GRAPH_ROOT}/me/drive/root/children?$skiptoken=page-2"
    calls: list[str] = []

    def get(url: str, *, headers: dict[str, str], timeout: int) -> httpx.Response:
        calls.append(url)
        assert headers["Authorization"] == "Bearer access"
        if url == first_url:
            return _http_response(url, {"value": [{"id": "first"}], "@odata.nextLink": next_url})
        assert url == next_url
        return _http_response(url, {"value": [{"id": "second"}]})

    monkeypatch.setattr("app.integrations.onedrive.httpx.get", get)

    rows = client._all_pages(first_url, credentials=credentials)

    assert [row["id"] for row in rows] == ["first", "second"]
    assert calls == [first_url, next_url]
    with pytest.raises(OneDriveOAuthInvalid):
        client._all_pages(
            "https://attacker.example.test/v1.0/steal",
            credentials=credentials,
        )


def test_graph_file_download_retries_throttling_with_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MicrosoftGraphClient(
        client_id="id", client_secret="secret", redirect_uri="https://callback"
    )
    credentials = OneDriveCredentials("access", "refresh", datetime.now(UTC) + timedelta(hours=1))
    calls: list[str] = []
    waits: list[float] = []

    def get(
        url: str,
        *,
        headers: dict[str, str],
        timeout: int,
        follow_redirects: bool,
    ) -> httpx.Response:
        calls.append(url)
        assert headers["Authorization"] == "Bearer access"
        assert timeout == 30
        assert follow_redirects is True
        if len(calls) == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "2"},
                request=httpx.Request("GET", url),
            )
        return httpx.Response(200, content=b"document bytes", request=httpx.Request("GET", url))

    monkeypatch.setattr("app.integrations.onedrive.httpx.get", get)
    monkeypatch.setattr("app.integrations.onedrive.time.sleep", waits.append)

    content = client.read_file(credentials=credentials, item_id="file-1")

    assert content == b"document bytes"
    assert calls == [f"{GRAPH_ROOT}/me/drive/items/file-1/content"] * 2
    assert waits == [2.0]


def test_parent_folder_ids_keep_nested_drive_hierarchy() -> None:
    assert MicrosoftGraphClient._parent_ids({"id": "root-item", "path": "/drive/root:"}) == (
        "root",
    )
    assert MicrosoftGraphClient._parent_ids(
        {"id": "department-id", "path": "/drive/root:/Department"}
    ) == ("department-id",)


def test_graph_delta_follows_pages_and_returns_delta_link_and_deleted_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MicrosoftGraphClient(
        client_id="id", client_secret="secret", redirect_uri="https://callback"
    )
    credentials = OneDriveCredentials("access", "refresh", datetime.now(UTC) + timedelta(hours=1))
    selection = type("Selection", (), {"kind": "all_accessible", "external_folder_id": ""})()
    next_url = f"{GRAPH_ROOT}/me/drive/root/delta?$skiptoken=page-2"
    delta_url = f"{GRAPH_ROOT}/me/drive/root/delta?$deltatoken=latest"
    calls: list[str] = []

    def get(url: str, *, headers: dict[str, str], timeout: int) -> httpx.Response:
        calls.append(url)
        assert headers["Authorization"] == "Bearer access"
        if len(calls) == 1:
            return _http_response(
                url,
                {
                    "value": [
                        {"id": "changed", "file": {"mimeType": "application/pdf"}},
                        {"id": "removed", "deleted": {"state": "deleted"}},
                    ],
                    "@odata.nextLink": next_url,
                },
            )
        assert url == next_url
        return _http_response(
            url, {"value": [{"id": "also-changed"}], "@odata.deltaLink": delta_url}
        )

    monkeypatch.setattr("app.integrations.onedrive.httpx.get", get)

    page = client.delta(credentials=credentials, selection=selection, cursor=None)

    assert isinstance(page, DeltaPage)
    assert [item["id"] for item in page.items] == ["changed", "removed", "also-changed"]
    assert page.items[1]["deleted"] == {"state": "deleted"}
    assert page.delta_link == delta_url
    assert calls == [
        f"{GRAPH_ROOT}/me/drive/root/delta?$select=id,name,file,folder,parentReference,webUrl,lastModifiedDateTime,deleted",
        next_url,
    ]


def test_graph_delta_resets_only_for_expired_tokens_or_deleted_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MicrosoftGraphClient(
        client_id="id", client_secret="secret", redirect_uri="https://callback"
    )
    credentials = OneDriveCredentials("access", "refresh", datetime.now(UTC) + timedelta(hours=1))
    url = f"{GRAPH_ROOT}/me/drive/root/delta?token=cursor"

    def request_with(status_code: int, payload: dict[str, object] | None = None) -> None:
        def get(url_arg: str, *, headers: dict[str, str], timeout: int) -> httpx.Response:
            assert url_arg == url
            return httpx.Response(
                status_code,
                json=payload,
                request=httpx.Request("GET", url_arg),
            )

        monkeypatch.setattr("app.integrations.onedrive.httpx.get", get)

    request_with(410)
    with pytest.raises(OneDriveDeltaExpired):
        client._get_json(url, credentials=credentials, allow_expired_delta=True)

    request_with(404, {"error": {"code": "itemNotFound"}})
    with pytest.raises(OneDriveDeltaExpired):
        client._get_json(url, credentials=credentials, allow_expired_delta=True)

    request_with(400, {"error": {"code": "invalidRequest"}})
    with pytest.raises(httpx.HTTPStatusError):
        client._get_json(url, credentials=credentials, allow_expired_delta=True)


def test_onedrive_discovery_keeps_per_selection_cursors_and_deleted_ids() -> None:
    cipher = OneDriveCipher(Fernet.generate_key().decode())
    credentials = OneDriveCredentials("access", "refresh", datetime.now(UTC) + timedelta(hours=1))
    selections = [
        type(
            "Selection",
            (),
            {
                "id": uuid4(),
                "kind": "folder",
                "external_folder_id": f"folder-{index}",
                "encrypted_delta_link": cipher.encrypt_cursor(
                    f"https://graph.microsoft.com/v1.0/cursor/{index}"
                ),
            },
        )()
        for index in (1, 2)
    ]

    class Client:
        def __init__(self) -> None:
            self.cursors: dict[object, str | None] = {}

        _external_id = staticmethod(MicrosoftGraphClient._external_id)
        _parent_ids = staticmethod(MicrosoftGraphClient._parent_ids)

        def delta(
            self, *, credentials: OneDriveCredentials, selection, cursor: str | None
        ) -> DeltaPage:
            assert credentials.access_token == "access"
            self.cursors[selection.id] = cursor
            if selection is selections[0]:
                return DeltaPage(
                    items=[
                        {
                            "id": "changed-item",
                            "name": "Current.docx",
                            "file": {"mimeType": "application/vnd.unknown"},
                            "parentReference": {"id": "folder-1"},
                        },
                        {
                            "id": "removed-item",
                            "deleted": {"state": "deleted"},
                            "parentReference": {"id": "folder-1"},
                        },
                    ],
                    delta_link="https://graph.microsoft.com/v1.0/delta/new-1",
                )
            return DeltaPage(
                items=[
                    {
                        "id": "removed-from-second",
                        "deleted": {"state": "deleted"},
                        "parentReference": {"id": "folder-2"},
                    }
                ],
                delta_link="https://graph.microsoft.com/v1.0/delta/new-2",
            )

    class Cipher:
        def decrypt_credentials(self, value: str) -> OneDriveCredentials:
            assert value == "encrypted-credentials"
            return credentials

        def decrypt_cursor(self, value: str) -> str:
            return cipher.decrypt_cursor(value)

    client = Client()
    result = OneDriveDocumentProvider(client, Cipher()).discover(
        encrypted_credentials="encrypted-credentials", selections=selections
    )

    assert client.cursors == {
        selections[0].id: "https://graph.microsoft.com/v1.0/cursor/1",
        selections[1].id: "https://graph.microsoft.com/v1.0/cursor/2",
    }
    assert result.full_snapshot is False
    assert result.delta_links == {
        selections[0].id: "https://graph.microsoft.com/v1.0/delta/new-1",
        selections[1].id: "https://graph.microsoft.com/v1.0/delta/new-2",
    }
    assert [(item.external_file_id, item.name) for item in result.documents] == [
        ("changed-item", "Current.docx")
    ]
    assert result.removed_file_ids == ("removed-from-second", "removed-item")


def test_root_file_delta_filters_hierarchy_and_merges_selected_folder_moves() -> None:
    cipher = OneDriveCipher(Fernet.generate_key().decode())
    credentials = OneDriveCredentials("access", "refresh", datetime.now(UTC) + timedelta(hours=1))
    encrypted_credentials = cipher.encrypt_credentials(credentials)
    selections = [
        type(
            "Selection",
            (),
            {
                "id": uuid4(),
                "kind": kind,
                "external_folder_id": folder_id,
                "encrypted_delta_link": cipher.encrypt_cursor(
                    f"https://graph.microsoft.com/v1.0/cursor/{kind}"
                ),
            },
        )()
        for kind, folder_id in (("root_files", ""), ("folder", "folder-1"))
    ]

    def file_item(item_id: str, parent_id: str) -> dict[str, object]:
        return {
            "id": item_id,
            "name": f"{item_id}.txt",
            "file": {"mimeType": "text/plain"},
            # Microsoft delta responses may omit parentReference.path; the
            # opaque parent ID is enough to distinguish direct root children.
            "parentReference": {"id": parent_id},
        }

    class Client:
        _external_id = staticmethod(MicrosoftGraphClient._external_id)
        _parent_ids = staticmethod(MicrosoftGraphClient._parent_ids)

        def root_id(self, *, credentials: OneDriveCredentials) -> str:
            assert credentials.access_token == "access"
            return "root-id"

        def delta(
            self, *, credentials: OneDriveCredentials, selection, cursor: str | None
        ) -> DeltaPage:
            assert cursor == f"https://graph.microsoft.com/v1.0/cursor/{selection.kind}"
            if selection.kind == "root_files":
                return DeltaPage(
                    items=[
                        file_item("root-file", "root-id"),
                        file_item("moved-out", "unselected-folder"),
                        {"id": "deleted", "deleted": {"state": "deleted"}},
                        file_item("moved-to-root", "root-id"),
                    ],
                    delta_link="https://graph.microsoft.com/v1.0/delta/root-latest",
                )
            return DeltaPage(
                items=[
                    file_item("moved-out", "folder-1"),
                    {"id": "moved-to-root", "deleted": {"state": "deleted"}},
                ],
                delta_link="https://graph.microsoft.com/v1.0/delta/folder-latest",
            )

    class Cipher:
        def __init__(self) -> None:
            self._delegate = cipher

        def decrypt_credentials(self, value: str) -> OneDriveCredentials:
            return self._delegate.decrypt_credentials(value)

        def decrypt_cursor(self, value: str) -> str:
            return self._delegate.decrypt_cursor(value)

    result = OneDriveDocumentProvider(Client(), Cipher()).discover(
        encrypted_credentials=encrypted_credentials, selections=selections
    )

    assert result.full_snapshot is False
    assert [item.external_file_id for item in result.documents] == [
        "moved-out",
        "moved-to-root",
        "root-file",
    ]
    assert result.removed_file_ids == ("deleted",)


def test_folder_delta_reenumerates_scope_when_a_folder_changes() -> None:
    cipher = OneDriveCipher(Fernet.generate_key().decode())
    credentials = OneDriveCredentials("access", "refresh", datetime.now(UTC) + timedelta(hours=1))
    selection = type(
        "Selection",
        (),
        {
            "id": uuid4(),
            "kind": "folder",
            "external_folder_id": "selected-folder",
            "encrypted_delta_link": cipher.encrypt_cursor(
                "https://graph.microsoft.com/v1.0/cursor/selected-folder"
            ),
        },
    )()
    nested_file = {
        "id": "new-descendant",
        "name": "New.pdf",
        "file": {"mimeType": "application/pdf"},
        "parentReference": {"id": "new-folder"},
    }

    class Client:
        _external_id = staticmethod(MicrosoftGraphClient._external_id)

        def delta(self, *, credentials, selection, cursor):
            assert cursor == "https://graph.microsoft.com/v1.0/cursor/selected-folder"
            return DeltaPage(
                items=[{"id": "new-folder", "folder": {"childCount": 1}}],
                delta_link="https://graph.microsoft.com/v1.0/delta/selected-folder-latest",
            )

        def list_files(self, *, credentials, selection):
            return [nested_file]

    class Cipher:
        def decrypt_credentials(self, value: str) -> OneDriveCredentials:
            assert value == "encrypted-credentials"
            return credentials

        def decrypt_cursor(self, value: str) -> str:
            return cipher.decrypt_cursor(value)

    provider = OneDriveDocumentProvider(Client(), Cipher())
    enumerated_files: dict[str, dict[str, object]] = {}
    provider._read_changed = lambda _credentials, files: enumerated_files.update(files) or []

    result = provider.discover(
        encrypted_credentials="encrypted-credentials", selections=[selection]
    )

    assert result.full_snapshot is True
    assert result.delta_links == {selection.id: None}
    assert result.removed_file_ids == ()
    assert enumerated_files == {"new-descendant": nested_file}
