from datetime import UTC, datetime, timedelta
from threading import Lock
from time import sleep
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.identity.auth import hash_secret
from app.identity.models import User, UserSession
from app.integrations.errors import SourceItemUnavailable
from app.integrations.google_drive import GoogleCredentials
from app.integrations.http import RemoteHttp
from app.integrations.models import DataSource, OAuthConnectionState
from app.integrations.notion import (
    NotionConnectionService,
    NotionDocumentProvider,
    NotionOAuthClient,
    NotionOAuthInvalid,
    NotionOAuthUnavailable,
    NotionPage,
    _blocks_to_text,
)
from app.organizations.models import Membership, MembershipRole, Organization


def test_notion_requires_oauth_configuration() -> None:
    with pytest.raises(NotionOAuthUnavailable):
        NotionOAuthClient(client_id=None, client_secret=None, redirect_uri=None).authorization_url(state="state")


def test_notion_authorization_url_contains_state_and_redirect() -> None:
    client = NotionOAuthClient(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="http://localhost:8000/data-sources/notion/oauth/callback",
    )
    url = client.authorization_url(state="signed-state")
    assert "client_id=client-id" in url
    assert "state=signed-state" in url
    assert "response_type=code" in url


def test_notion_client_reads_the_oauth_owner_email_from_its_bot_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    client = NotionOAuthClient(client_id="id", client_secret="secret", redirect_uri="http://callback")

    def request(method: str, path: str, *, credentials: GoogleCredentials, **kwargs: object) -> dict[str, object]:
        assert method == "GET"
        assert path == "/v1/users/me"
        assert credentials.access_token == "token"
        assert not kwargs
        return {"object": "user", "type": "bot", "bot": {"owner": {"type": "user", "user": {"person": {"email": "Notion.Owner@Example.Test"}}}}}

    monkeypatch.setattr(client, "_request", request)

    assert client.account_email(credentials=GoogleCredentials("token", None, None)) == "notion.owner@example.test"


def test_notion_blocks_are_normalized_to_searchable_text() -> None:
    blocks = [
        {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "First paragraph"}]}},
        {"type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "A heading"}]}},
        {"type": "code", "code": {"rich_text": [{"plain_text": "print('ok')"}]}},
    ]
    assert _blocks_to_text(blocks) == "First paragraph\n\nA heading\n\nprint('ok')"


def test_notion_page_retains_parent_and_complete_title() -> None:
    page = NotionOAuthClient._page({
        "id": "child", "parent": {"type": "page_id", "page_id": "parent"},
        "properties": {"Name": {"type": "title", "title": [
            {"plain_text": "Run"}, {"plain_text": "book"},
        ]}},
    })
    assert page.title == "Runbook"
    assert page.parent_ids == ("parent",)


def test_notion_child_pages_are_boundaries_not_parent_content(monkeypatch: pytest.MonkeyPatch) -> None:
    client = NotionOAuthClient(client_id="i", client_secret="s", redirect_uri="cb")
    calls = []

    def request(method, path, **kwargs):
        calls.append(path)
        return {"results": [{"id": "child", "type": "child_page", "has_children": True,
                             "child_page": {"title": "Child"}}], "has_more": False}

    monkeypatch.setattr(client, "_request", request)
    blocks = client.page_blocks(credentials=GoogleCredentials("token", None, None), page_id="parent")
    assert calls == ["/v1/blocks/parent/children"]
    assert _blocks_to_text(blocks) == ""


def test_notion_tables_equations_and_references_keep_their_data() -> None:
    text = _blocks_to_text([
        {"type": "table_row", "table_row": {"cells": [[{"plain_text": "Product"}], [{"plain_text": "Price"}]]}},
        {"type": "equation", "equation": {"expression": "x = 2"}},
        {"type": "link_to_page", "link_to_page": {"type": "page_id", "page_id": "other"}},
        {"type": "bookmark", "bookmark": {"url": "https://example.test/reference"}},
    ])
    assert "Product | Price" in text
    assert "x = 2" in text
    assert "https://www.notion.so/other" in text
    assert "https://example.test/reference" in text


def test_notion_selection_indexes_descendants_and_uses_distinct_container_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    client = NotionOAuthClient(client_id="i", client_secret="s", redirect_uri="cb")
    reads = []

    def page(id, title, parent=None):
        return {"id": id, "object": "page", "url": f"https://notion.so/{id}",
                "parent": {"type": "page_id", "page_id": parent} if parent else {"type": "workspace"},
                "properties": {"Name": {"type": "title", "title": [{"plain_text": title}]}}}

    def request(method, path, **kwargs):
        if path == "/v1/search":
            objects = [page("parent", "Parent"), page("unrelated", "Unrelated")]
            if kwargs["json"].get("filter", {}).get("value") == "data_source":
                objects = []
            return {"results": objects, "has_more": False}
        if path == "/v1/pages/child":
            return page("child", "Child", "parent")
        if path == "/v1/blocks/parent/children":
            reads.append("parent")
            return {"results": [
                {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Parent body"}]}},
                {"id": "child", "type": "child_page", "has_children": True, "child_page": {"title": "Child"}},
                {"type": "link_to_page", "link_to_page": {"type": "page_id", "page_id": "unrelated"}},
            ], "has_more": False}
        if path == "/v1/blocks/child/children":
            reads.append("child")
            return {"results": [{"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Child body"}]}}], "has_more": False}
        raise AssertionError(path)

    class Cipher:
        def decrypt(self, value):
            return GoogleCredentials("token", None, None)

    monkeypatch.setattr(client, "_request", request)
    provider = NotionDocumentProvider(client, Cipher())
    selections = [type("Selection", (), {"kind": "folder", "external_folder_id": "parent"})()]
    result = provider.discover(encrypted_credentials="encrypted", selections=selections)
    assert sorted(reads) == ["child", "parent"]
    docs = {doc.external_file_id: doc for doc in result.documents}
    assert set(docs) == {"parent", "child"}
    assert "Child body" not in docs["parent"].text
    assert "unrelated" in docs["parent"].text
    assert docs["child"].parent_ids == ("notion:container:parent",)
    assert docs["parent"].parent_ids == ("notion:container:parent",)
    assert docs["parent"].name == "Conteúdo de Parent"
    folders = provider.folders_for_selections(encrypted_credentials="encrypted", selections=selections)
    assert [(folder.id, folder.name) for folder in folders] == [("notion:container:parent", "Parent")]


def test_notion_unchanged_pages_still_refresh_library_metadata() -> None:
    edited = datetime.now(UTC)

    class Cipher:
        def decrypt(self, value):
            return GoogleCredentials("token", None, None)

    class Client:
        def list_pages(self, **kwargs):
            return [NotionPage("parent", "Parent", "", edited),
                    NotionPage("child", "Renamed", "", edited, ("parent",))]

        def page_blocks(self, **kwargs):
            raise AssertionError("unchanged content must not be read")

    provider = NotionDocumentProvider(Client(), Cipher())
    result = provider.discover(encrypted_credentials="encrypted",
        selections=[type("Selection", (), {"kind": "folder", "external_folder_id": "parent"})()],
        known_documents={"parent": (edited, "indexed"), "child": (edited, "indexed")})
    assert result.documents == []
    assert result.removed_file_ids == ()
    assert [(doc.external_file_id, doc.name, doc.parent_ids) for doc in result.catalog_documents] == [
        ("child", "Renamed", ("notion:container:parent",)),
        ("parent", "Conteúdo de Parent", ("notion:container:parent",)),
    ]


def test_notion_database_rows_and_block_children_are_paginated_without_flattening(monkeypatch: pytest.MonkeyPatch) -> None:
    client = NotionOAuthClient(client_id="i", client_secret="s", redirect_uri="cb")
    requests = []
    database = {"object": "database", "id": "db", "title": [{"plain_text": "Projects"}], "parent": {"type": "workspace"}, "data_sources": [{"id": "collection", "name": "Items"}, {"id": "collection2", "name": "Other"}]}
    data_source = {"object": "data_source", "id": "collection", "title": [{"plain_text": "Items"}], "parent": {"type": "database_id", "database_id": "db"}}
    row = {"object": "page", "id": "row", "parent": {"type": "data_source_id", "data_source_id": "collection"},
           "properties": {"Name": {"type": "title", "title": [{"plain_text": "Apollo"}]},
                          "Status": {"type": "select", "select": {"name": "Ready"}},
                          "Budget": {"type": "number", "number": 0}}}

    def request(method, path, **kwargs):
        requests.append((path, kwargs))
        if path == "/v1/search":
            return {"results": [data_source] if kwargs["json"]["filter"]["value"] == "data_source" else [], "has_more": False}
        if path == "/v1/databases/db":
            return database
        if path == "/v1/data_sources/collection2":
            return dict(data_source, id="collection2", title=[{"plain_text": "Other"}])
        if path == "/v1/data_sources/collection2/query":
            return {"results": [], "has_more": False}
        if path == "/v1/data_sources/collection/query":
            if kwargs["json"].get("start_cursor") == "next-row":
                return {"results": [dict(row, id="row2")], "has_more": False}
            return {"results": [row], "has_more": True, "next_cursor": "next-row"}
        if path == "/v1/blocks/row/children":
            if kwargs["params"].get("start_cursor") == "next-block":
                return {"results": [{"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Second"}]}}], "has_more": False}
            return {"results": [{"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "First"}]}}], "has_more": True, "next_cursor": "next-block"}
        if path == "/v1/blocks/row2/children":
            return {"results": [], "has_more": False}
        raise AssertionError(path)

    class Cipher:
        def decrypt(self, value):
            return GoogleCredentials("token", None, None)

    monkeypatch.setattr(client, "_request", request)
    provider = NotionDocumentProvider(client, Cipher())
    selections = [type("Selection", (), {"kind": "folder", "external_folder_id": "db"})()]
    result = provider.discover(encrypted_credentials="encrypted", selections=selections)
    docs = {doc.external_file_id: doc for doc in result.documents}
    assert set(docs) == {"row", "row2"}
    assert "Status: Ready" in docs["row"].text
    assert "Budget: 0" in docs["row"].text
    assert "First\n\nSecond" in docs["row"].text
    assert docs["row2"].parent_ids == ("notion:container:collection",)
    assert [f.id for f in provider.folders_for_selections(encrypted_credentials="encrypted", selections=selections)] == ["notion:container:collection", "notion:container:collection2", "notion:container:db"]


def test_notion_rich_text_links_are_references_not_descendants() -> None:
    text = _blocks_to_text([{"type": "paragraph", "paragraph": {"rich_text": [
        {"plain_text": "Policy", "href": "https://www.notion.so/policy"},
    ]}}])
    assert "Policy" in text
    assert "https://www.notion.so/policy" in text


def test_notion_new_child_of_unchanged_page_is_discovered_before_search_indexes_it(monkeypatch) -> None:
    edited = datetime.now(UTC)
    client = NotionOAuthClient(client_id="i", client_secret="s", redirect_uri="cb")
    monkeypatch.setattr(client, "list_pages", lambda **_: [NotionPage("parent", "Parent", "", edited)])
    monkeypatch.setattr(client, "list_databases", lambda **_: [])
    monkeypatch.setattr(client, "retrieve_page", lambda **_: NotionPage("child", "Child", "", edited, ("parent",), "page_id"))
    monkeypatch.setattr(client, "page_blocks", lambda *, page_id, **_: [
        {"id": "child", "type": "child_page", "child_page": {"title": "Child"}}
    ] if page_id == "parent" else [{"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "New body"}]}}])
    cipher = type("Cipher", (), {"decrypt": lambda *_: GoogleCredentials("token", None, None)})()
    result = NotionDocumentProvider(client, cipher).discover(encrypted_credentials="encrypted",
        selections=[type("Selection", (), {"kind": "folder", "external_folder_id": "parent"})()],
        known_documents={"parent": (edited, "indexed")})
    assert [document.external_file_id for document in result.documents] == ["child"]
    assert {document.external_file_id for document in result.catalog_documents} == {"parent", "child"}
    assert result.removed_file_ids == ()


def test_notion_search_absence_does_not_remove_a_still_accessible_known_page(monkeypatch) -> None:
    client = NotionOAuthClient(client_id="i", client_secret="s", redirect_uri="cb")
    edited = datetime.now(UTC)
    monkeypatch.setattr(client, "list_pages", lambda **_: [])
    monkeypatch.setattr(client, "list_databases", lambda **_: [])
    monkeypatch.setattr(client, "retrieve_page", lambda **_: NotionPage("known", "Known", "", edited))
    monkeypatch.setattr(client, "page_blocks", lambda **_: [])
    cipher = type("Cipher", (), {"decrypt": lambda *_: GoogleCredentials("token", None, None)})()
    result = NotionDocumentProvider(client, cipher).discover(encrypted_credentials="encrypted",
        selections=[type("Selection", (), {"kind": "all_accessible", "external_folder_id": ""})()],
        known_documents={"known": (edited, "indexed")})
    assert result.removed_file_ids == ()
    assert [document.external_file_id for document in result.catalog_documents] == ["known"]


def test_notion_cyclic_parents_do_not_create_a_cyclic_library_tree() -> None:
    class Client:
        def list_pages(self, **_):
            return [NotionPage("a", "A", "", None, ("b",)), NotionPage("b", "B", "", None, ("a",))]

        def page_blocks(self, **_):
            return [{"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "body"}]}}]

    cipher = type("Cipher", (), {"decrypt": lambda *_: GoogleCredentials("token", None, None)})()
    provider = NotionDocumentProvider(Client(), cipher)
    selections = [type("Selection", (), {"kind": "all_accessible", "external_folder_id": ""})()]
    provider.discover(encrypted_credentials="encrypted", selections=selections)
    assert all(not folder.parent_ids for folder in provider.folders_for_selections(encrypted_credentials="encrypted", selections=selections))


def test_notion_page_keeps_source_metadata() -> None:
    page = NotionPage("page-id", "Runbook", "https://notion.so/page-id", datetime.now(UTC))
    assert page.id == "page-id"
    assert page.title == "Runbook"
    assert page.url.endswith("page-id")


def test_notion_page_blocks_include_nested_children(monkeypatch: pytest.MonkeyPatch) -> None:
    client = NotionOAuthClient(client_id="id", client_secret="secret", redirect_uri="http://callback")
    calls: list[str] = []

    def request(method: str, path: str, *, credentials: GoogleCredentials, **kwargs: object) -> dict[str, object]:
        del method, credentials, kwargs
        calls.append(path)
        if path == "/v1/blocks/page-id/children":
            return {
                "results": [{"id": "toggle-id", "type": "toggle", "has_children": True, "toggle": {"rich_text": []}}],
                "has_more": False,
            }
        return {
            "results": [{"id": "nested-id", "type": "paragraph", "has_children": False, "paragraph": {"rich_text": [{"plain_text": "Nested content"}]}}],
            "has_more": False,
        }

    monkeypatch.setattr(client, "_request", request)
    blocks = client.page_blocks(credentials=GoogleCredentials("token", None, None), page_id="page-id")

    assert [block["id"] for block in blocks] == ["toggle-id", "nested-id"]
    assert calls == ["/v1/blocks/page-id/children", "/v1/blocks/toggle-id/children"]
    assert _blocks_to_text(blocks) == "Nested content"


def test_notion_discover_skips_empty_metadata_pages() -> None:
    class FakeCipher:
        def decrypt(self, value: str) -> GoogleCredentials:
            assert value == "encrypted"
            return GoogleCredentials("token", None, None)

    class FakeClient:
        def list_pages(self, *, credentials: GoogleCredentials) -> list[NotionPage]:
            assert credentials.access_token == "token"
            return [
                NotionPage("empty", "Profile", "https://notion.so/empty", None),
                NotionPage("content", "Runbook", "https://notion.so/content", None),
            ]

        def page_blocks(self, *, credentials: GoogleCredentials, page_id: str) -> list[dict[str, object]]:
            assert credentials.access_token == "token"
            return [] if page_id == "empty" else [{"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Runbook body"}]}}]

    provider = NotionDocumentProvider(FakeClient(), FakeCipher())
    documents = provider.discover(
        encrypted_credentials="encrypted",
        selections=[type("Selection", (), {"kind": "all_accessible", "external_folder_id": ""})()],
    )

    assert [(document.external_file_id, document.name) for document in documents.documents] == [("content", "Runbook")]


def test_notion_discover_reads_pages_concurrently_with_stable_order() -> None:
    class Cipher:
        def decrypt(self, value: str) -> GoogleCredentials:
            return GoogleCredentials("token", None, None)

    class Client:
        def __init__(self) -> None:
            self.lock = Lock()
            self.active = 0
            self.peak = 0

        def list_pages(self, *, credentials: GoogleCredentials) -> list[NotionPage]:
            return [NotionPage(str(index), f"Page {index}", "", None) for index in range(5, 0, -1)]

        def page_blocks(self, *, credentials: GoogleCredentials, page_id: str) -> list[dict[str, object]]:
            with self.lock:
                self.active += 1
                self.peak = max(self.peak, self.active)
            sleep(0.01)
            with self.lock:
                self.active -= 1
            return [{"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": page_id}]}}]

    client = Client()
    documents = NotionDocumentProvider(client, Cipher()).discover(
        encrypted_credentials="encrypted",
        selections=[type("Selection", (), {"kind": "all_accessible", "external_folder_id": ""})()],
    )
    assert [document.external_file_id for document in documents.documents] == ["1", "2", "3", "4", "5"]
    assert client.peak == 2


def test_notion_incremental_reads_only_changed_pages_and_reconciles_removals() -> None:
    edited = datetime.now(UTC)

    class Cipher:
        def decrypt(self, value: str) -> GoogleCredentials:
            return GoogleCredentials("token", None, None)

    class Client:
        def __init__(self) -> None:
            self.read_ids: list[str] = []

        def list_pages(self, *, credentials: GoogleCredentials) -> list[NotionPage]:
            return [
                NotionPage("unchanged", "Unchanged", "", edited),
                NotionPage("changed", "Changed", "", edited),
                NotionPage("new", "New", "", edited),
                NotionPage("failed", "Failed before", "", edited),
            ]

        def page_blocks(self, *, credentials: GoogleCredentials, page_id: str) -> list[dict[str, object]]:
            self.read_ids.append(page_id)
            return [{"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": page_id}]}}]

    client = Client()
    discovery = NotionDocumentProvider(client, Cipher()).discover(
        encrypted_credentials="encrypted",
        selections=[type("Selection", (), {"kind": "all_accessible", "external_folder_id": ""})()],
        known_documents={
            "unchanged": (edited, "indexed"),
            "changed": (edited - timedelta(seconds=1), "indexed"),
            "failed": (edited, "failed"),
            "removed": (edited, "indexed"),
        },
    )

    assert discovery.full_snapshot is False
    assert [document.external_file_id for document in discovery.documents] == ["changed", "failed", "new"]
    assert sorted(client.read_ids) == ["changed", "failed", "new"]
    assert discovery.removed_file_ids == ("removed",)


def test_notion_missing_selected_page_is_reported_removed() -> None:
    class Cipher:
        def decrypt(self, value: str) -> GoogleCredentials:
            return GoogleCredentials("token", None, None)

    class Client:
        def list_pages(self, *, credentials: GoogleCredentials) -> list[NotionPage]:
            return []

        def page_blocks(self, *, credentials: GoogleCredentials, page_id: str) -> list[dict[str, object]]:
            raise AssertionError("missing page must not be read")

    discovery = NotionDocumentProvider(Client(), Cipher()).discover(
        encrypted_credentials="encrypted",
        selections=[type("Selection", (), {"kind": "folder", "external_folder_id": "missing"})()],
        known_documents={"missing": (datetime.now(UTC), "indexed")},
    )

    assert discovery.full_snapshot is False
    assert discovery.documents == []
    assert discovery.removed_file_ids == ("missing",)


def test_notion_page_edited_to_empty_content_is_removed_from_index() -> None:
    edited = datetime.now(UTC)

    class Cipher:
        def decrypt(self, value: str) -> GoogleCredentials:
            return GoogleCredentials("token", None, None)

    class Client:
        def list_pages(self, *, credentials: GoogleCredentials) -> list[NotionPage]:
            return [NotionPage("page", "Page", "", edited)]

        def page_blocks(self, *, credentials: GoogleCredentials, page_id: str) -> list[dict[str, object]]:
            return []

    discovery = NotionDocumentProvider(Client(), Cipher()).discover(
        encrypted_credentials="encrypted",
        selections=[type("Selection", (), {"kind": "all_accessible", "external_folder_id": ""})()],
        known_documents={"page": (edited - timedelta(seconds=1), "indexed")},
    )

    assert discovery.full_snapshot is False
    assert discovery.documents == []
    assert discovery.removed_file_ids == ("page",)


def test_notion_manual_reprocess_forces_page_read_when_timestamp_is_unchanged() -> None:
    edited = datetime.now(UTC)

    class Cipher:
        def decrypt(self, value: str) -> GoogleCredentials:
            return GoogleCredentials("token", None, None)

    class Client:
        def __init__(self) -> None:
            self.read_ids: list[str] = []

        def list_pages(self, *, credentials: GoogleCredentials) -> list[NotionPage]:
            return [NotionPage("page", "Page", "", edited)]

        def page_blocks(self, *, credentials: GoogleCredentials, page_id: str) -> list[dict[str, object]]:
            self.read_ids.append(page_id)
            return [{"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "body"}]}}]

    client = Client()
    discovery = NotionDocumentProvider(client, Cipher()).discover(
        encrypted_credentials="encrypted",
        selections=[type("Selection", (), {"kind": "all_accessible", "external_folder_id": ""})()],
        known_documents={"page": (edited, "indexed")},
        force_file_ids={"page"},
    )

    assert client.read_ids == ["page"]
    assert [document.external_file_id for document in discovery.documents] == ["page"]


def test_notion_oauth_cannot_reconnect_a_google_source() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    class Client:
        def authorization_url(self, *, state: str) -> str:
            return f"https://notion.example.test/oauth?state={state}"

        def exchange_code(self, *, code: str) -> GoogleCredentials:
            return GoogleCredentials("notion-token", None, None)

        def account_email(self, *, credentials: GoogleCredentials) -> str | None:
            return None

    class Cipher:
        def encrypt(self, credentials: GoogleCredentials) -> str:
            return "notion-ciphertext"

    try:
        with Session(engine) as session:
            organization = Organization(name="Acme")
            user = User(email=f"admin-{uuid4()}@example.test")
            session.add_all([organization, user])
            session.flush()
            session.add(Membership(organization_id=organization.id, user_id=user.id, role=MembershipRole.ADMIN, is_active=True))
            session.add(UserSession(user_id=user.id, secret_hash=hash_secret("session"), expires_at=datetime.now(UTC) + timedelta(hours=1)))
            google_source = DataSource(organization_id=organization.id, provider="google_drive", encrypted_credentials="google-ciphertext", status="connected", connected_by_user_id=user.id)
            session.add(google_source)
            session.flush()
            service = NotionConnectionService(session, Cipher(), Client())

            with pytest.raises(NotionOAuthInvalid):
                service.begin(scope=OrganizationScope(organization.id), user_id=user.id, session_secret="session", source_id=google_source.id)

            session.add(OAuthConnectionState(
                organization_id=organization.id, user_id=user.id, source_id=google_source.id,
                session_hash=hash_secret("session"), state_hash=hash_secret("state"),
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
            ))
            session.flush()
            with pytest.raises(NotionOAuthInvalid):
                service.complete(raw_state="state", code="code", session_secret="session")
            assert google_source.provider == "google_drive"
            assert google_source.encrypted_credentials == "google-ciphertext"
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_notion_manual_reprocess_forces_page_read_when_timestamp_is_unchanged_full_snapshot() -> None:
    edited = datetime.now(UTC)

    class Cipher:
        def decrypt(self, value: str) -> GoogleCredentials:
            return GoogleCredentials("token", None, None)

    class Client:
        def __init__(self) -> None:
            self.read_ids: list[str] = []

        def list_pages(self, *, credentials: GoogleCredentials) -> list[NotionPage]:
            return [NotionPage("page", "Page", "", edited)]

        def page_blocks(self, *, credentials: GoogleCredentials, page_id: str) -> list[dict[str, object]]:
            self.read_ids.append(page_id)
            return [{"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "body"}]}}]

    client = Client()
    discovery = NotionDocumentProvider(client, Cipher()).discover(
        encrypted_credentials="encrypted",
        selections=[type("Selection", (), {"kind": "all_accessible", "external_folder_id": ""})()],
        known_documents={"page": (edited, "indexed")},
        force_full=True,
    )

    assert client.read_ids == ["page"]
    assert [document.external_file_id for document in discovery.documents] == ["page"]


def _reply(status: int, payload: dict | None = None, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json=payload or {}, headers=headers or {}, request=httpx.Request("POST", "https://api.notion.com/v1/search"))


def test_notion_429_is_retried_with_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[float] = []
    replies = iter([_reply(429, headers={"Retry-After": "1"}), _reply(200, {"results": [], "has_more": False})])
    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: next(replies))
    client = NotionOAuthClient(
        client_id="i", client_secret="s", redirect_uri="https://cb",
        http=RemoteHttp(sleep=waits.append, monotonic=lambda: 0.0, jitter=lambda: 1.0),
    )
    assert client.list_pages(credentials=GoogleCredentials("token", None, None)) == []
    assert waits == [1.0]


def test_notion_403_and_404_are_item_failures_and_401_is_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.integrations.notion import NotionRemoteUnauthorized

    client = NotionOAuthClient(client_id="i", client_secret="s", redirect_uri="https://cb")
    credentials = GoogleCredentials("token", None, None)
    for status, expected in ((403, SourceItemUnavailable), (404, SourceItemUnavailable), (401, NotionRemoteUnauthorized)):
        monkeypatch.setattr(httpx, "get", lambda url, status=status, **kwargs: _reply(status))
        with pytest.raises(expected):
            client._request("GET", "/v1/blocks/p/children", credentials=credentials)


def test_notion_restricted_page_is_dropped_from_the_index_without_failing_the_sync() -> None:
    class FakeCipher:
        def decrypt(self, value: str) -> GoogleCredentials:
            return GoogleCredentials("token", None, None)

    class FakeClient:
        def list_pages(self, *, credentials: GoogleCredentials) -> list[NotionPage]:
            return [NotionPage("p1", "Runbook", "https://notion.so/p1", None), NotionPage("p2", "Private", "https://notion.so/p2", None)]

        def page_blocks(self, *, credentials: GoogleCredentials, page_id: str) -> list[dict[str, object]]:
            if page_id == "p2":
                raise SourceItemUnavailable("restricted_resource")
            return [{"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Runbook body"}]}}]

    result = NotionDocumentProvider(FakeClient(), FakeCipher()).discover(
        encrypted_credentials="encrypted",
        selections=[type("Selection", (), {"kind": "all_accessible", "external_folder_id": ""})()],
    )

    assert [document.external_file_id for document in result.documents] == ["p1"]
    assert "p2" in result.removed_file_ids
