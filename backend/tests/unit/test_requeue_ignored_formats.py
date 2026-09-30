from types import SimpleNamespace

from sqlalchemy import select
from test_ingestion_service import create_workspace
from test_ingestion_service import session as session  # noqa: PLC0414 -- pytest fixture re-export

from app.ingestion.models import ProcessingJob
from app.knowledge.models import Document
from scripts.requeue_ignored import requeue


def test_requeue_is_dry_run_and_scoped_to_selected_folder(session):
    org, _, folder = create_workspace(session)
    documents = [
        Document(
            organization_id=org.id,
            workspace_folder_id=folder.id,
            external_file_id=id,
            name=name,
            mime_type=mime,
            source_url="",
            index_status="ignored",
            error_code="unsupported_file_type",
            content_hash="old",
        )
        for id, name, mime in [
            ("csv", "base.csv", "text/plain"),
            ("photo", "photo.png", "image/png"),
        ]
    ]
    session.add_all(documents)
    session.commit()
    settings = SimpleNamespace(new_formats_enabled=True, active_document_limit=500)
    count, jobs = requeue(session, folder_ids=[folder.id], settings=settings, apply=False)
    assert count == 1 and jobs == []
    assert documents[0].content_hash == "old"
    assert not list(session.scalars(select(ProcessingJob)))
    count, jobs = requeue(session, folder_ids=[folder.id], settings=settings, apply=True)
    assert count == 1 and len(jobs) == 1
    assert documents[0].content_hash == ""
    assert documents[1].content_hash == "old"
