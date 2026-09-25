"""Runtime registry for source providers."""

from collections.abc import Callable

from app.core.config import Settings
from app.ingestion.google_drive import GoogleDriveDocumentProvider
from app.integrations.base import ProviderCapabilities, ProviderNotConfigured, SourceProvider
from app.integrations.google_drive import CredentialCipher, GoogleDriveOAuthClient
from app.integrations.notion import NotionDocumentProvider, NotionOAuthClient
from app.integrations.onedrive import MicrosoftGraphClient, OneDriveCipher, OneDriveDocumentProvider


class GoogleDriveProviderAdapter:
    key = "google_drive"
    capabilities = ProviderCapabilities(
        supports_oauth=True,
        supports_hierarchical_scopes=True,
        supports_incremental_sync=False,
    )

    def __init__(self, settings: Settings):
        self._provider = GoogleDriveDocumentProvider(
            GoogleDriveOAuthClient(
                client_id=settings.google_oauth_client_id,
                client_secret=settings.google_oauth_client_secret.get_secret_value()
                if settings.google_oauth_client_secret
                else None,
                redirect_uri=settings.google_oauth_redirect_uri,
            ),
            CredentialCipher(
                settings.google_token_encryption_key.get_secret_value()
                if settings.google_token_encryption_key
                else None
            ),
        )

    def discover(self, *, encrypted_credentials, selections):
        return self._provider.discover(
            encrypted_credentials=encrypted_credentials or "",
            selections=selections,
        )

    def folders(self, *, encrypted_credentials):
        return self._provider.folders(encrypted_credentials=encrypted_credentials or "")


class NotionProviderAdapter:
    key = "notion"
    capabilities = ProviderCapabilities(
        supports_oauth=True,
        supports_hierarchical_scopes=True,
        supports_incremental_sync=False,
    )

    def __init__(self, settings: Settings):
        key = settings.notion_token_encryption_key or settings.google_token_encryption_key
        self._provider = NotionDocumentProvider(
            NotionOAuthClient(
                client_id=settings.notion_oauth_client_id,
                client_secret=settings.notion_oauth_client_secret.get_secret_value()
                if settings.notion_oauth_client_secret
                else None,
                redirect_uri=settings.notion_oauth_redirect_uri,
            ),
            CredentialCipher(key.get_secret_value() if key else None),
        )

    def discover(self, *, encrypted_credentials, selections):
        return self._provider.discover(
            encrypted_credentials=encrypted_credentials, selections=selections
        )

    def folders(self, *, encrypted_credentials):
        return self._provider.folders(encrypted_credentials=encrypted_credentials)


class OneDriveProviderAdapter:
    key = "onedrive"
    capabilities = ProviderCapabilities(
        supports_oauth=True,
        supports_hierarchical_scopes=True,
        supports_incremental_sync=True,
    )

    def __init__(self, settings: Settings):
        key = settings.microsoft_token_encryption_key
        self._provider = OneDriveDocumentProvider(
            MicrosoftGraphClient(
                client_id=settings.microsoft_oauth_client_id,
                client_secret=settings.microsoft_oauth_client_secret.get_secret_value()
                if settings.microsoft_oauth_client_secret
                else None,
                redirect_uri=settings.microsoft_oauth_redirect_uri,
            ),
            OneDriveCipher(key.get_secret_value() if key else None),
        )

    @property
    def updated_encrypted_credentials(self):
        return self._provider.updated_encrypted_credentials

    def encrypt_delta_link(self, value: str) -> str:
        return self._provider.cipher.encrypt_cursor(value)

    def discover(self, *, encrypted_credentials, selections):
        return self._provider.discover(
            encrypted_credentials=encrypted_credentials, selections=selections
        )

    def folders(self, *, encrypted_credentials):
        return self._provider.folders(encrypted_credentials=encrypted_credentials)


class IntegrationRegistry:
    def __init__(self, settings: Settings):
        self._factories: dict[str, Callable[[], SourceProvider]] = {
            "google_drive": lambda: GoogleDriveProviderAdapter(settings),
            "notion": lambda: NotionProviderAdapter(settings),
            "onedrive": lambda: OneDriveProviderAdapter(settings),
        }

    def get(self, provider: str) -> SourceProvider:
        factory = self._factories.get(provider)
        if factory is None:
            raise ProviderNotConfigured(f"integration provider is not configured: {provider}")
        return factory()
