from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.ingestion import tasks
from app.ingestion.service import DiscoveredDocument
from app.knowledge.questions import AIProviderRateLimited


@pytest.mark.parametrize("enabled", [False, True])
def test_task_force_reads_newly_eligible_ignored_files(monkeypatch, enabled):
    from app.library import manual_sync
    monkeypatch.setattr(manual_sync, "update_progress", lambda *_, **__: None)
    monkeypatch.setattr(manual_sync, "scoped_documents", lambda _s, _j, docs, *_: docs)
    org, folder_id, source_id, job_id = (uuid4() for _ in range(4))
    job = SimpleNamespace(
        id=job_id, organization_id=org, workspace_folder_id=folder_id, run_token="run"
    )
    folder = SimpleNamespace(id=folder_id, organization_id=org, source_id=source_id)
    source = SimpleNamespace(
        id=source_id,
        organization_id=org,
        provider="google_drive",
        encrypted_credentials="cipher",
        status="connected",
    )
    known = [
        SimpleNamespace(
            external_file_id="csv",
            modified_at=None,
            name="base.csv",
            mime_type="text/plain",
            index_status="ignored",
            error_code="unsupported_file_type",
        ),
        SimpleNamespace(
            external_file_id="image",
            modified_at=None,
            name="photo.png",
            mime_type="image/png",
            index_status="ignored",
            error_code="unsupported_file_type",
        ),
    ]
    session = MagicMock()
    session.__enter__.return_value = session
    session.scalar.side_effect = [folder, source]
    session.scalars.side_effect = [
        [SimpleNamespace(kind="all_accessible", external_folder_id="")],
        known,
    ]
    service = MagicMock()
    service.claim.return_value = job
    service.apply_reconciliation.return_value = job
    provider = MagicMock()
    provider.folders.return_value = []
    provider.discover.return_value = [
        DiscoveredDocument("id", "Name", "application/pdf", "", text="body")
    ]
    embedding = MagicMock()
    embedding.embed_workspace.side_effect = AIProviderRateLimited(None)
    settings = SimpleNamespace(
        new_formats_enabled=enabled,
        active_document_limit=500,
        google_oauth_client_id=None,
        google_oauth_client_secret=None,
        google_oauth_redirect_uri=None,
        google_token_encryption_key=None,
        openai_api_key=None,
    )
    monkeypatch.setattr(tasks, "get_settings", lambda: settings)
    monkeypatch.setattr(tasks, "build_engine", lambda _: None)
    monkeypatch.setattr(tasks, "build_session_factory", lambda _: lambda: session)
    monkeypatch.setattr(tasks, "IngestionService", lambda _: service)
    monkeypatch.setattr(
        tasks, "IntegrationRegistry", lambda *a, **k: SimpleNamespace(get=lambda *a, **k: provider)
    )
    monkeypatch.setattr(tasks, "EmbeddingService", lambda *a, **k: embedding)
    monkeypatch.setattr(tasks.reconcile_workspace_folder, "max_retries", 0)
    assert tasks.reconcile_workspace_folder.apply(args=[str(job_id)], throw=True).successful()
    assert provider.discover.call_args.kwargs["force_file_ids"] == ({"csv"} if enabled else set())
    assert ("text/csv" in provider.eligible_mime_types) is enabled
