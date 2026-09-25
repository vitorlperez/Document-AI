from datetime import UTC, datetime, timedelta
from threading import Lock
from time import sleep
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.identity.auth import hash_secret
from app.identity.models import User, UserSession
from app.integrations.google_drive import GoogleCredentials
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

    assert [(document.external_file_id, document.name) for document in documents] == [("content", "Runbook")]


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
    assert [document.external_file_id for document in documents] == ["1", "2", "3", "4", "5"]
    assert client.peak == 2


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
