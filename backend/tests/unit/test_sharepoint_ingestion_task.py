from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.core.config import Settings
from app.ingestion.service import DiscoveryResult
from app.integrations.google_drive import RemoteFolder


def _run_worker(monkeypatch, *, provider_name: str, provider) -> dict:
    """Runs one reconciliation with fakes and returns the projection kwargs."""
    from app.ingestion import tasks

    organization_id, workspace_folder_id, source_id, job_id = (uuid4() for _ in range(4))
    job = SimpleNamespace(
        id=job_id,
        organization_id=organization_id,
        workspace_folder_id=workspace_folder_id,
        run_token="active-run-token",
    )
    folder = SimpleNamespace(
        id=workspace_folder_id, organization_id=organization_id, source_id=source_id
    )
    source = SimpleNamespace(
        id=source_id,
        provider=provider_name,
        encrypted_credentials="credentials",
        status="connected",
        last_synced_at=None,
    )
    selection = SimpleNamespace(
        id=uuid4(), kind="folder", external_folder_id="b!d1|01F", encrypted_delta_link=None
    )
    projected: dict = {}

    class FakeSession:
        def __init__(self) -> None:
            self.scalar_values = iter([folder, source])
            self.scalars_calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def commit(self) -> None:
            return None

        def rollback(self) -> None:
            raise AssertionError("successful sync must not roll back")

        def refresh(self, _: object) -> None:
            return None

        def scalar(self, _: object):
            return next(self.scalar_values)

        def scalars(self, _: object):
            self.scalars_calls += 1
            return [selection] if self.scalars_calls == 1 else []

    session = FakeSession()

    class FakeIngestionService:
        def __init__(self, _: FakeSession) -> None:
            return None

        def claim(self, *, job_id):
            return job

        def apply_reconciliation(self, **_: object):
            return job

        def has_failed_documents(self, **_: object) -> bool:
            return False

        def finalize_reconciliation(self, **_: object):
            return SimpleNamespace(completed_at=datetime.now(UTC))

    class FakeRegistry:
        def __init__(self, _: object) -> None:
            return None

        def get(self, name: str, **_: object):
            assert name == provider_name
            return provider

    class FakeEmbeddingService:
        def __init__(self, *_: object) -> None:
            return None

        def embed_workspace(self, **_: object) -> int:
            return 0

    class FakeLibraryService:
        def __init__(self, _: FakeSession) -> None:
            return None

        def filter_excluded_content(self, *, documents, folders, **_: object):
            return documents, folders

        def project_successful_sync(self, **kwargs: object) -> None:
            projected.update(kwargs)

    monkeypatch.setattr(tasks, "get_settings", lambda: SimpleNamespace(openai_api_key=None))
    monkeypatch.setattr(tasks, "build_engine", lambda _: object())
    monkeypatch.setattr(tasks, "build_session_factory", lambda _: lambda: session)
    monkeypatch.setattr(tasks, "IngestionService", FakeIngestionService)
    monkeypatch.setattr(tasks, "IntegrationRegistry", FakeRegistry)
    monkeypatch.setattr(tasks, "EmbeddingService", FakeEmbeddingService)
    monkeypatch.setattr(tasks, "OpenAIQuestionProvider", lambda _: object())
    monkeypatch.setattr(tasks, "LibraryService", FakeLibraryService)

    assert tasks.reconcile_workspace_folder.apply(args=[str(job_id)], throw=True).successful()
    projected["selection"] = selection
    return projected


class _Provider:
    updated_encrypted_credentials = None

    def __init__(self) -> None:
        self.folders_calls = 0

    def discover(self, **_: object) -> DiscoveryResult:
        return DiscoveryResult(documents=[], delta_links={}, full_snapshot=True)

    def folders(self, **_: object) -> list[RemoteFolder]:
        self.folders_calls += 1
        return [RemoteFolder("catalog", "Catalog", ())]

    def encrypt_delta_link(self, value: str) -> str:
        return value


def test_worker_uses_folders_for_selections_when_provider_supports_it(monkeypatch) -> None:
    nodes = [RemoteFolder("site|s", "Site", ()), RemoteFolder("b!d1|01F", "Pasta", ("site|s",))]

    class SelectionAware(_Provider):
        def folders_for_selections(self, *, encrypted_credentials, selections):
            self.selections = selections
            return nodes

    provider = SelectionAware()
    projected = _run_worker(monkeypatch, provider_name="sharepoint", provider=provider)
    assert projected["folders"] == nodes
    assert provider.selections == [projected["selection"]]
    assert provider.folders_calls == 0


def test_provider_without_folders_for_selections_still_uses_folders(monkeypatch) -> None:
    provider = _Provider()
    projected = _run_worker(monkeypatch, provider_name="onedrive", provider=provider)
    assert projected["folders"] == [RemoteFolder("catalog", "Catalog", ())]
    assert provider.folders_calls == 1


def test_sharepoint_settings_defaults() -> None:
    settings = Settings(database_url="postgresql+psycopg://u:p@localhost:5432/db")
    assert settings.microsoft_sharepoint_redirect_uri is None
    assert settings.sharepoint_download_workers == 2
    assert settings.sharepoint_max_file_bytes == 52_428_800
    assert settings.sharepoint_catalog_max_sites == 200
    assert settings.cipher_keys("sharepoint") == settings.cipher_keys("onedrive")
