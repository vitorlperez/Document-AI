import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.core.config import Settings
from app.integrations.google_drive import CredentialCipher, GoogleCredentials, GoogleOAuthInvalid
from app.integrations.keyring import build_fernet, rotate_token

DB = "postgresql+psycopg://u:p@localhost/db"


def key() -> str:
    return Fernet.generate_key().decode()


def test_credentials_encrypted_with_the_old_key_still_decrypt_and_rotate_to_the_new_one() -> None:
    old, new = key(), key()
    legacy = CredentialCipher(old).encrypt(GoogleCredentials("a", "r", None))
    cipher = CredentialCipher(new, fallback_keys=[old])
    assert cipher.decrypt(legacy).access_token == "a"
    rotated = cipher.rotate(legacy)
    assert CredentialCipher(new).decrypt(rotated).access_token == "a"  # new key alone is enough
    with pytest.raises(GoogleOAuthInvalid):
        CredentialCipher(old).decrypt(rotated)  # and the old key no longer reads it


def test_no_usable_key_means_not_configured() -> None:
    assert build_fernet([None, ""]) is None


def test_notion_keys_are_own_first_and_google_only_as_legacy_fallback() -> None:
    google, notion = key(), key()
    with_fallback = Settings(
        database_url=DB, google_token_encryption_key=google, notion_token_encryption_key=notion
    )
    assert with_fallback.cipher_keys("notion") == [notion, google]
    no_fallback = Settings(
        database_url=DB,
        google_token_encryption_key=google,
        notion_token_encryption_key=notion,
        notion_token_encryption_legacy_fallback=False,
    )
    assert no_fallback.cipher_keys("notion") == [notion]
    assert no_fallback.cipher_keys("google_drive") == [google]


def test_production_rejects_a_key_reused_across_providers() -> None:
    shared = key()
    with pytest.raises(ValidationError):
        Settings(
            database_url=DB,
            environment="production",
            google_token_encryption_key=shared,
            notion_token_encryption_key=shared,
        )
    with pytest.raises(ValidationError):
        Settings(
            database_url=DB,
            environment="production",
            google_token_encryption_key=shared,
            microsoft_token_encryption_key=shared,
        )
    Settings(
        database_url=DB,
        environment="development",
        google_token_encryption_key=shared,
        notion_token_encryption_key=shared,
    )  # dev keeps working


def test_production_notion_requires_own_key_even_during_legacy_window():
    with pytest.raises(ValidationError):
        Settings(
            database_url=DB,
            environment="production",
            notion_oauth_client_id="enabled",
            google_token_encryption_key=key(),
            notion_token_encryption_legacy_fallback=True,
        )


def test_disabled_legacy_fallback_does_not_encrypt_with_google_key():
    settings = Settings(
        database_url=DB,
        google_token_encryption_key=key(),
        notion_token_encryption_legacy_fallback=False,
    )
    assert settings.cipher_keys("notion") == [None]


def test_onedrive_rotates_credentials_and_cursor():
    from datetime import UTC, datetime

    from app.integrations.onedrive import OneDriveCipher, OneDriveCredentials

    old, new = key(), key()
    cipher = OneDriveCipher(new, fallback_keys=[old])
    credentials = OneDriveCipher(old).encrypt_credentials(
        OneDriveCredentials("a", "r", datetime.now(UTC))
    )
    cursor = OneDriveCipher(old).encrypt_cursor("https://graph.microsoft.com/v1.0/cursor")
    primary = OneDriveCipher(new)
    assert primary.decrypt_credentials(cipher.rotate(credentials)).access_token == "a"
    assert primary.decrypt_cursor(cipher.rotate(cursor)).endswith("/cursor")


def test_rotate_token_preserves_plaintext_using_primary_key():
    old, new = key(), key()
    token = Fernet(old.encode()).encrypt(b"payload").decode()
    ring = build_fernet([new, old])
    assert Fernet(new.encode()).decrypt(rotate_token(ring, token).encode()) == b"payload"
