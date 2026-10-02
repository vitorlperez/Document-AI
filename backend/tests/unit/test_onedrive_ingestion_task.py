from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.ingestion.service import DiscoveryResult


def test_onedrive_delta_cursor_commits_with_successful_ingestion(monkeypatch) -> None:
    from app.ingestion import tasks
    from app.library import manual_sync

    monkeypatch.setattr(manual_sync, "update_progress", lambda *_, **__: None)
    monkeypatch.setattr(manual_sync, "scoped_documents", lambda _s, _j, docs, *_: docs)

    organization_id, workspace_folder_id, source_id, job_id, selection_id = (
        uuid4() for _ in range(5)
    )
    completed_job = SimpleNamespace(completed_at=datetime.now(UTC))
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
        provider="onedrive",
        encrypted_credentials="old-credentials",
        status="connected",
        last_synced_at=None,
    )
    selection = SimpleNamespace(
        id=selection_id,
        kind="folder",
        external_folder_id="folder-1",
        encrypted_delta_link="old-cursor",
    )
    failed_document = SimpleNamespace(
        external_file_id="failed-file", index_status="failed", modified_at=None, content_hash=""
    )
    reprocess_document = SimpleNamespace(
        external_file_id="manual-file", index_status="indexed",
                modified_at=None, content_hash=""
    )
    clean_document = SimpleNamespace(
        external_file_id="clean-file", index_status="indexed",
                modified_at=None, content_hash="known-hash"
    )
    discovery = DiscoveryResult(
        documents=[],
        delta_links={selection_id: "https://graph.microsoft.com/v1.0/delta?new=cursor"},
        full_snapshot=False,
    )

    class FakeSession:
        def __init__(self) -> None:
            self.committed_cursors: list[str | None] = []
            self.scalar_values = iter([folder, source])
            self.scalars_calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def commit(self) -> None:
            self.committed_cursors.append(selection.encrypted_delta_link)

        def rollback(self) -> None:
            raise AssertionError("successful OneDrive sync must not roll back")

        def refresh(self, _: object) -> None:
            return None

        def scalar(self, _: object):
            return next(self.scalar_values)

        def scalars(self, _: object):
            self.scalars_calls += 1
            return (
                [selection]
                if self.scalars_calls == 1
                else [failed_document, reprocess_document, clean_document]
            )

    session = FakeSession()

    class FakeIngestionService:
        def __init__(self, _: FakeSession) -> None:
            return None

        def claim(self, *, job_id):
            assert job_id == job.id
            return job

        def apply_reconciliation(self, **kwargs):
            assert kwargs["documents"] == discovery
            return job

        def has_failed_documents(self, **_: object) -> bool:
            return False

        def finalize_reconciliation(self, **_: object):
            return completed_job

    class FakeProvider:
        updated_encrypted_credentials = "new-credentials"
        force_file_ids: set[str] | None = None

        def discover(self, **_: object) -> DiscoveryResult:
            self.force_file_ids = _["force_file_ids"]
            return discovery

        def folders(self, **_: object) -> list[object]:
            return []

        def encrypt_delta_link(self, value: str) -> str:
            return f"encrypted:{value}"

    provider = FakeProvider()

    class FakeRegistry:
        def __init__(self, _: object) -> None:
            return None

        def get(self, name: str, **context):
            assert name == "onedrive"
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

        def project_successful_sync(self, **_: object) -> None:
            return None

    settings = SimpleNamespace(openai_api_key=None)
    monkeypatch.setattr(tasks, "get_settings", lambda: settings)
    monkeypatch.setattr(tasks, "build_engine", lambda _: object())
    monkeypatch.setattr(tasks, "build_session_factory", lambda _: lambda: session)
    monkeypatch.setattr(tasks, "IngestionService", FakeIngestionService)
    monkeypatch.setattr(tasks, "IntegrationRegistry", FakeRegistry)
    monkeypatch.setattr(tasks, "EmbeddingService", FakeEmbeddingService)
    monkeypatch.setattr(tasks, "OpenAIQuestionProvider", lambda _: object())
    monkeypatch.setattr(tasks, "LibraryService", FakeLibraryService)

    result = tasks.reconcile_workspace_folder.apply(args=[str(job_id)], throw=True)

    assert result.successful()
    assert (
        selection.encrypted_delta_link
        == "encrypted:https://graph.microsoft.com/v1.0/delta?new=cursor"
    )
    assert source.encrypted_credentials == "new-credentials"
    assert provider.force_file_ids == {"failed-file", "manual-file"}
    assert session.committed_cursors[-1] == selection.encrypted_delta_link
    assert all(cursor == "old-cursor" for cursor in session.committed_cursors[:-1])
