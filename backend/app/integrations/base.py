"""Provider-neutral contracts for external knowledge sources."""

from dataclasses import dataclass
from typing import Protocol

from app.ingestion.service import DiscoveredDocument, DiscoveryResult
from app.workspaces.models import WorkspaceFolderSelection


@dataclass(frozen=True)
class ProviderCapabilities:
    supports_oauth: bool
    supports_hierarchical_scopes: bool
    supports_incremental_sync: bool


class SourceProvider(Protocol):
    key: str
    capabilities: ProviderCapabilities

    def discover(
        self,
        *,
        encrypted_credentials: str | None,
        selections: list[WorkspaceFolderSelection],
    ) -> list[DiscoveredDocument] | DiscoveryResult: ...

    def folders(self, *, encrypted_credentials: str | None): ...


class ProviderNotConfigured(RuntimeError):
    pass
