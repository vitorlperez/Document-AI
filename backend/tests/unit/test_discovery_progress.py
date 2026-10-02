"""Extraction progress callbacks execute on the caller, never the parser threads."""
from threading import get_ident
from types import SimpleNamespace

import pytest

from app.ingestion.google_drive import GoogleDriveDocumentProvider
from app.integrations.onedrive import OneDriveDocumentProvider
from app.integrations.sharepoint import SharePointDocumentProvider
from tests.sync_helpers import doc


@pytest.mark.parametrize("provider_class", [GoogleDriveDocumentProvider, OneDriveDocumentProvider, SharePointDocumentProvider])
def test_each_extracted_file_reports_progress_on_the_worker_thread(provider_class, monkeypatch):
    provider = object.__new__(provider_class)
    provider.extraction_workers = provider.max_workers = 2
    thread = get_ident()
    events = []

    def progress(processed, total):
        assert get_ident() == thread
        events.append((processed, total))

    if provider_class is GoogleDriveDocumentProvider:
        monkeypatch.setattr(provider, "_extract", lambda **kwargs: doc(kwargs["remote_file"].id))
        result = provider._extract_files("credentials", [SimpleNamespace(id=str(i)) for i in range(3)], progress)
    else:
        monkeypatch.setattr(provider, "_read_one", lambda credentials, item: doc(item["id"]))
        result = provider._read_changed(None, {str(i): {"id": str(i)} for i in range(3)}, progress)
    assert len(result) == 3
    assert events == [(1, 3), (2, 3), (3, 3)]
