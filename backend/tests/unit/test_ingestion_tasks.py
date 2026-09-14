from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ingestion.service import DiscoveredDocument
from app.knowledge.questions import AIProviderRateLimited


def test_exhausted_embedding_rate_limit_rolls_back_and_marks_job_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Celery boundary must retain the prior committed snapshot on a 429."""
    from app.ingestion import tasks

    organization_id, workspace_folder_id, source_id, job_id = (uuid4() for _ in range(4))
    run_token = "active-run-token"
    job = SimpleNamespace(
        id=job_id,
        organization_id=organization_id,
        workspace_folder_id=workspace_folder_id,
        run_token=run_token,
    )
    folder = SimpleNamespace(id=workspace_folder_id, organization_id=organization_id, source_id=source_id)
    source = SimpleNamespace(
        id=source_id,
        organization_id=organization_id,
        encrypted_credentials="ciphertext",
        status="connected",
        last_synced_at=None,
    )
    selection = SimpleNamespace(kind="all_accessible", external_folder_id="")

    class FakeSession:
        def __init__(self) -> None:
            self.commit_calls = 0
            self.rollback_calls = 0
            self.scalar_values = iter([folder, source])

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def commit(self) -> None:
            self.commit_calls += 1

        def rollback(self) -> None:
            self.rollback_calls += 1

        def refresh(self, _: object) -> None:
            return None

        def scalar(self, _: object):
            return next(self.scalar_values)

        def scalars(self, _: object):
            return [selection]

    session = FakeSession()

    failed: list[tuple[object, str, str]] = []
    released: list[tuple[object, str]] = []

    class FakeIngestionService:

        def __init__(self, _: FakeSession) -> None:
            return None

        def claim(self, *, job_id: object):
            assert job_id == job.id
            return job

        def apply_reconciliation(self, **_: object):
            return job

        def fail(self, *, job_id: object, error_code: str, expected_run_token: str):
            failed.append((job_id, error_code, expected_run_token))
            return job

        def release_for_retry(self, *, job_id: object, expected_run_token: str):
            released.append((job_id, expected_run_token))
            return job

    class FakeDriveProvider:
        def __init__(self, *_: object) -> None:
            return None

        def discover(self, **_: object) -> list[DiscoveredDocument]:
            return [
                DiscoveredDocument(
                    external_file_id="file-1",
                    name="Brief",
                    mime_type="application/vnd.google-apps.document",
                    source_url="https://drive.example.test/file-1",
                    text="Approved scope",
                )
            ]

        def folders(self, **_: object) -> list[object]:
            return []

    class RateLimitedEmbeddingService:
        def __init__(self, *_: object) -> None:
            return None

        def embed_workspace(self, **_: object) -> int:
            raise AIProviderRateLimited(None)

    settings = SimpleNamespace(
        google_oauth_client_id=None,
        google_oauth_client_secret=None,
        google_oauth_redirect_uri=None,
        google_token_encryption_key=None,
        openai_api_key=None,
    )
    monkeypatch.setattr(tasks, "get_settings", lambda: settings)
    monkeypatch.setattr(tasks, "build_engine", lambda _: object())
    monkeypatch.setattr(tasks, "build_session_factory", lambda _: lambda: session)
    monkeypatch.setattr(tasks, "IngestionService", FakeIngestionService)
    monkeypatch.setattr(tasks, "GoogleDriveDocumentProvider", FakeDriveProvider)
    monkeypatch.setattr(tasks, "EmbeddingService", RateLimitedEmbeddingService)
    monkeypatch.setattr(tasks.reconcile_workspace_folder, "max_retries", 0)

    result = tasks.reconcile_workspace_folder.apply(args=[str(job_id)], throw=True)

    assert result.successful()
    assert session.rollback_calls == 1
    assert released == []
    assert failed == [(job_id, "embedding_failed", run_token)]
    assert session.commit_calls == 2
