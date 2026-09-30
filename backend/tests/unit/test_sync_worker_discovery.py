"""Invariant (a) at the worker: a space without data ignores a stale cursor."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.ingestion.service import DiscoveryResult


# (a) at the worker boundary: a space without data ignores a stale cursor.
def _run_task(monkeypatch, *, known_rows: list) -> dict:
    from app.ingestion import tasks

    organization_id, workspace_folder_id, source_id, job_id = (uuid4() for _ in range(4))
    job = SimpleNamespace(id=job_id, organization_id=organization_id,
                          workspace_folder_id=workspace_folder_id, run_token="token")
    folder = SimpleNamespace(id=workspace_folder_id, organization_id=organization_id, source_id=source_id)
    source = SimpleNamespace(id=source_id, provider="google_drive", encrypted_credentials="c",
                             status="connected", last_synced_at=None)
    selection = SimpleNamespace(id=uuid4(), kind="folder", external_folder_id="tda",
                                encrypted_delta_link="stale-cursor")
    seen: dict = {}

    class FakeSession:
        scalar_values = iter([folder, source])
        calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def commit(self):
            return None

        def rollback(self):
            raise AssertionError("unexpected rollback")

        def refresh(self, _):
            return None

        def scalar(self, _):
            return next(self.scalar_values)

        def scalars(self, _):
            FakeSession.calls += 1
            return [selection] if FakeSession.calls == 1 else known_rows

    class Service:
        def __init__(self, _):
            return None

        def claim(self, **_):
            return job

        def apply_reconciliation(self, **_):
            return job

        def has_failed_documents(self, **_):
            return False

        def finalize_reconciliation(self, **_):
            return SimpleNamespace(completed_at=datetime.now(UTC))

    class Provider:
        updated_encrypted_credentials = None

        def discover(self, **kwargs):
            seen.update(kwargs)
            return DiscoveryResult(documents=[], delta_links={}, full_snapshot=True)

        def folders(self, **_):
            return []

    class Library:
        def __init__(self, _):
            return None

        def filter_excluded_content(self, *, documents, folders, **kwargs):
            seen["filter_kwargs"] = kwargs
            return documents, folders

        def project_successful_sync(self, **kwargs):
            seen["project_kwargs"] = kwargs

    monkeypatch.setattr(tasks, "get_settings", lambda: SimpleNamespace(openai_api_key=None))
    monkeypatch.setattr(tasks, "build_engine", lambda _: object())
    monkeypatch.setattr(tasks, "build_session_factory", lambda _: lambda: FakeSession())
    monkeypatch.setattr(tasks, "IngestionService", Service)
    monkeypatch.setattr(tasks, "IntegrationRegistry",
                        lambda _: SimpleNamespace(get=lambda name, **__: Provider()))
    monkeypatch.setattr(tasks, "EmbeddingService",
                        lambda *_: SimpleNamespace(embed_workspace=lambda **__: 0))
    monkeypatch.setattr(tasks, "OpenAIQuestionProvider", lambda _: object())
    monkeypatch.setattr(tasks, "LibraryService", Library)
    assert tasks.reconcile_workspace_folder.apply(args=[str(job_id)], throw=True).successful()
    seen["workspace_folder_id"] = workspace_folder_id
    return seen


def test_worker_forces_full_discovery_for_space_without_data(monkeypatch) -> None:
    seen = _run_task(monkeypatch, known_rows=[])
    assert seen["force_full"] is True
    assert seen["filter_kwargs"]["workspace_folder_id"] == seen["workspace_folder_id"]
    assert seen["project_kwargs"]["workspace_folder_id"] == seen["workspace_folder_id"]


def test_worker_keeps_incremental_discovery_for_space_with_data(monkeypatch) -> None:
    indexed = SimpleNamespace(external_file_id="a", index_status="indexed", content_hash="h",
                              error_code=None, modified_at=None, name="a.pdf", mime_type="application/pdf")
    seen = _run_task(monkeypatch, known_rows=[indexed])
    assert "force_full" not in seen
