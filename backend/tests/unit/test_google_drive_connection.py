import importlib
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings
from app.core.scoping import OrganizationScope
from app.identity.models import UserSession
from app.integrations.google_drive import (
    GOOGLE_DRIVE_READONLY_SCOPE,
    CredentialCipher,
    GoogleAccessDenied,
    GoogleConnectionService,
    GoogleCredentials,
    GoogleDriveOAuthClient,
    GoogleOAuthInvalid,
    GoogleOAuthUnavailable,
    GoogleRemoteUnauthorized,
    RemoteFolder,
)
from app.integrations.models import OAuthConnectionState
from app.organizations.models import Membership, MembershipRole


class FakeSession:
    def __init__(self, scalar_results: list[object | None]) -> None:
        self.scalar_results = list(scalar_results)
        self.added: list[object] = []
        self.flush_count = 0

    def scalar(self, statement: object) -> object | None:
        return self.scalar_results.pop(0)

    def scalars(self, statement: object) -> list[object]:
        return []

    def add(self, value: object) -> None:
        self.added.append(value)

    def flush(self) -> None:
        self.flush_count += 1


class FakeGooglePort:
    def __init__(self) -> None:
        self.authorization_calls: list[dict[str, str]] = []
        self.codes: list[str] = []
        self.credentials = GoogleCredentials("google-access-token", "google-refresh-token", None)
        self.authorized_email = "drive-owner@example.test"
        self.folders = [RemoteFolder("folder-1", "Client A")]

    def authorization_url(self, *, state: str, scope: str) -> str:
        self.authorization_calls.append({"state": state, "scope": scope})
        return f"https://google.example.test/auth?state={state}"

    def exchange_code(self, *, code: str) -> GoogleCredentials:
        self.codes.append(code)
        return self.credentials

    def account_email(self, *, credentials: GoogleCredentials) -> str | None:
        assert credentials == self.credentials
        return self.authorized_email

    def list_folders(self, *, credentials: GoogleCredentials) -> list[RemoteFolder]:
        assert credentials == self.credentials
        return self.folders


def active_member(organization_id, user_id, role: MembershipRole) -> Membership:
    return Membership(
        organization_id=organization_id,
        user_id=user_id,
        role=role,
        is_active=True,
    )


def test_credential_cipher_is_reversible_only_with_key_and_never_returns_plaintext() -> None:
    cipher = CredentialCipher(Fernet.generate_key().decode())
    credentials = GoogleCredentials("access-secret", "refresh-secret", datetime.now(UTC))

    ciphertext = cipher.encrypt(credentials)

    assert ciphertext != credentials.access_token
    assert credentials.refresh_token not in ciphertext
    assert cipher.decrypt(ciphertext) == credentials


def test_credential_cipher_requires_configured_key() -> None:
    with pytest.raises(GoogleOAuthUnavailable, match="encryption"):
        CredentialCipher(None).encrypt(GoogleCredentials("access", None, None))


def test_begin_binds_one_time_hashed_state_to_admin_org_and_session() -> None:
    organization_id, admin_id = uuid4(), uuid4()
    session = FakeSession([active_member(organization_id, admin_id, MembershipRole.ADMIN)])
    port = FakeGooglePort()
    service = GoogleConnectionService(session, CredentialCipher(Fernet.generate_key().decode()))

    url = service.begin(
        scope=OrganizationScope(organization_id),
        user_id=admin_id,
        session_secret="server-session-secret",
        port=port,
    )

    state = session.added[0]
    assert isinstance(state, OAuthConnectionState)
    assert url.endswith(port.authorization_calls[0]["state"])
    assert port.authorization_calls[0]["scope"] == GOOGLE_DRIVE_READONLY_SCOPE
    assert state.organization_id == organization_id
    assert state.user_id == admin_id
    assert state.state_hash == sha256(port.authorization_calls[0]["state"].encode()).hexdigest()
    assert state.session_hash == sha256(b"server-session-secret").hexdigest()
    assert port.authorization_calls[0]["state"] not in state.state_hash
    assert state.expires_at > datetime.now(UTC)


def test_member_cannot_start_google_connection() -> None:
    organization_id, member_id = uuid4(), uuid4()
    session = FakeSession([None])
    service = GoogleConnectionService(session, CredentialCipher(Fernet.generate_key().decode()))

    with pytest.raises(GoogleAccessDenied):
        service.begin(
            scope=OrganizationScope(organization_id),
            user_id=member_id,
            session_secret="session-secret",
            port=FakeGooglePort(),
        )
    assert session.added == []


def test_complete_rejects_mismatched_state_without_exchanging_code() -> None:
    session = FakeSession([None])
    port = FakeGooglePort()
    service = GoogleConnectionService(session, CredentialCipher(Fernet.generate_key().decode()))

    with pytest.raises(GoogleOAuthInvalid):
        service.complete(raw_state="wrong-state", code="authorization-code", session_secret="session", port=port)
    assert port.codes == []
    assert session.added == []


def test_complete_encrypts_credentials_marks_state_consumed_and_never_stores_tokens() -> None:
    organization_id, admin_id = uuid4(), uuid4()
    raw_state, session_secret = "oauth-state", "server-session"
    state = OAuthConnectionState(
        organization_id=organization_id,
        user_id=admin_id,
        session_hash=sha256(session_secret.encode()).hexdigest(),
        state_hash=sha256(raw_state.encode()).hexdigest(),
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    active_session = UserSession(
        user_id=admin_id,
        secret_hash=sha256(session_secret.encode()).hexdigest(),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session = FakeSession([state, active_session, active_member(organization_id, admin_id, MembershipRole.OWNER)])
    cipher = CredentialCipher(Fernet.generate_key().decode())
    port = FakeGooglePort()

    source = GoogleConnectionService(session, cipher).complete(
        raw_state=raw_state,
        code="authorization-code",
        session_secret=session_secret,
        port=port,
    )

    assert port.codes == ["authorization-code"]
    assert state.consumed_at is not None
    assert source.organization_id == organization_id
    assert source.provider == "google_drive"
    assert source.status == "connected"
    assert source.account_email == "drive-owner@example.test"
    assert source.encrypted_credentials != "google-access-token"
    assert "google-access-token" not in source.encrypted_credentials
    assert cipher.decrypt(source.encrypted_credentials) == port.credentials


def test_application_uses_real_google_oauth_client_when_constructed(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db")
    main = importlib.import_module("app.main")
    settings = Settings(
        database_url="postgresql+psycopg://test_user:not-a-secret@localhost:5432/test_db",
        google_oauth_client_id="google-client-id",
        google_oauth_client_secret="google-client-secret",
        google_oauth_redirect_uri="https://api.example.test/callback",
    )

    app = main.create_app(settings)

    assert isinstance(app.state.google_drive_port, GoogleDriveOAuthClient)
    authorization_url = app.state.google_drive_port.authorization_url(
        state="opaque-state", scope=GOOGLE_DRIVE_READONLY_SCOPE
    )
    assert "accounts.google.com" in authorization_url
    assert "client_id=google-client-id" in authorization_url
    assert "scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fdrive.readonly" in authorization_url


def test_google_client_reads_authorized_account_email_without_expanding_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def get(url: str, **kwargs: object) -> httpx.Response:
        calls.append({"url": url, **kwargs})
        return httpx.Response(
            200,
            json={"user": {"emailAddress": "Drive.Owner@Example.Test"}},
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr("app.integrations.google_drive.httpx.get", get)
    client = GoogleDriveOAuthClient(client_id="id", client_secret="secret", redirect_uri="https://example.test/callback")

    email = client.account_email(credentials=GoogleCredentials("access-token", None, None))

    assert email == "drive.owner@example.test"
    assert calls == [{"url": "https://www.googleapis.com/drive/v3/about", "params": {"fields": "user(emailAddress)"}, "headers": {"Authorization": "Bearer access-token"}, "timeout": 10}]


def test_google_client_marks_unauthorized_account_metadata_as_remote_unauthorized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def get(url: str, **_: object) -> httpx.Response:
        return httpx.Response(403, request=httpx.Request("GET", url))

    monkeypatch.setattr("app.integrations.google_drive.httpx.get", get)
    client = GoogleDriveOAuthClient(client_id="id", client_secret="secret", redirect_uri="https://example.test/callback")

    with pytest.raises(GoogleRemoteUnauthorized):
        client.account_email(credentials=GoogleCredentials("access-token", None, None))
