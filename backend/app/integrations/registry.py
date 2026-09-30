"""Runtime registry for source providers."""

from collections.abc import Callable

from app.core.config import Settings
from app.ingestion.extraction import eligible_mime_types
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
        supports_incremental_sync=True,
    )

    def __init__(self, settings: Settings, *, session=None, source_id=None):
        keys = settings.cipher_keys("google_drive")
        self._provider = GoogleDriveDocumentProvider(
            GoogleDriveOAuthClient(
                client_id=settings.google_oauth_client_id,
                client_secret=settings.google_oauth_client_secret.get_secret_value()
                if settings.google_oauth_client_secret
                else None,
                redirect_uri=settings.google_oauth_redirect_uri,
            ),
            CredentialCipher(keys[0], fallback_keys=keys[1:]),
            session=session, source_id=source_id,
        )
        self.eligible_mime_types = eligible_mime_types(settings)

    @property
    def eligible_mime_types(self):
        return self._provider.eligible_mime_types

    @eligible_mime_types.setter
    def eligible_mime_types(self, value):
        self._provider.eligible_mime_types = value


    def discover(self, *, encrypted_credentials, selections, known_documents=None, force_file_ids=None, force_full=False):
        return self._provider.discover(
            encrypted_credentials=encrypted_credentials or "",
            selections=selections,
            force_file_ids=force_file_ids,
            force_full=force_full,
        )

    @property
    def updated_encrypted_credentials(self):
        return self._provider.updated_encrypted_credentials

    def folders(self, *, encrypted_credentials):
        return self._provider.folders(encrypted_credentials=encrypted_credentials or "")

    def encrypt_delta_link(self, value: str) -> str:
        return self._provider.cipher.encrypt_cursor(value)


class NotionProviderAdapter:
    key = "notion"
    capabilities = ProviderCapabilities(
        supports_oauth=True,
        supports_hierarchical_scopes=True,
        supports_incremental_sync=False,
    )

    def __init__(self, settings: Settings):
        keys = settings.cipher_keys("notion")
        self._provider = NotionDocumentProvider(
            NotionOAuthClient(
                client_id=settings.notion_oauth_client_id,
                client_secret=settings.notion_oauth_client_secret.get_secret_value()
                if settings.notion_oauth_client_secret
                else None,
                redirect_uri=settings.notion_oauth_redirect_uri,
            ),
            CredentialCipher(keys[0], fallback_keys=keys[1:]),
        )

    def discover(self, *, encrypted_credentials, selections, known_documents=None, force_file_ids=None, force_full=False):
        return self._provider.discover(
            encrypted_credentials=encrypted_credentials,
            selections=selections,
            known_documents=known_documents,
            force_file_ids=force_file_ids,
            force_full=force_full,
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
        keys = settings.cipher_keys("onedrive")
        self._provider = OneDriveDocumentProvider(
            MicrosoftGraphClient(
                client_id=settings.microsoft_oauth_client_id,
                client_secret=settings.microsoft_oauth_client_secret.get_secret_value()
                if settings.microsoft_oauth_client_secret
                else None,
                redirect_uri=settings.microsoft_oauth_redirect_uri,
            ),
            OneDriveCipher(keys[0], fallback_keys=keys[1:]),
        )

        self.eligible_mime_types = eligible_mime_types(settings)

    @property
    def eligible_mime_types(self):
        return self._provider.eligible_mime_types

    @eligible_mime_types.setter
    def eligible_mime_types(self, value):
        self._provider.eligible_mime_types = value


    @property
    def updated_encrypted_credentials(self):
        return self._provider.updated_encrypted_credentials

    def encrypt_delta_link(self, value: str) -> str:
        return self._provider.cipher.encrypt_cursor(value)

    def discover(self, *, encrypted_credentials, selections, known_documents=None, force_file_ids=None, force_full=False):
        return self._provider.discover(
            encrypted_credentials=encrypted_credentials,
            selections=selections,
            force_file_ids=force_file_ids,
            force_full=force_full,
        )

    def folders(self, *, encrypted_credentials):
        return self._provider.folders(encrypted_credentials=encrypted_credentials)


class IntegrationRegistry:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._factories: dict[str, Callable[[], SourceProvider]] = {
            "google_drive": lambda: GoogleDriveProviderAdapter(settings),
            "notion": lambda: NotionProviderAdapter(settings),
            "onedrive": lambda: OneDriveProviderAdapter(settings),
        }

    def get(self, provider: str, *, session=None, source_id=None) -> SourceProvider:
        if provider == "google_drive":
            return GoogleDriveProviderAdapter(self._settings, session=session, source_id=source_id)
        factory = self._factories.get(provider)
        if factory is None:
            raise ProviderNotConfigured(f"integration provider is not configured: {provider}")
        return factory()
