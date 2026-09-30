"""Preview/requeue formerly unsupported files in explicitly selected folders.

Run from backend: .venv/bin/python -m scripts.requeue_ignored --folder UUID [--apply]
"""

import argparse
from uuid import UUID

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import build_engine, build_session_factory
from app.core.scoping import OrganizationScope
from app.ingestion.extraction import eligible_mime_types
from app.ingestion.extraction.mime import normalize_mime_type
from app.ingestion.service import IngestionService
from app.knowledge.models import Document


def requeue(session, *, folder_ids, settings, apply=False):
    eligible = eligible_mime_types(settings)
    documents = [
        document
        for document in session.scalars(
            select(Document).where(
                Document.workspace_folder_id.in_(folder_ids),
                Document.index_status == "ignored",
                Document.error_code == "unsupported_file_type",
            )
        )
        if normalize_mime_type(document.name, document.mime_type) in eligible
    ]
    jobs = []
    if apply:
        service = IngestionService(session, settings=settings)
        folders = {}
        for document in documents:
            document.content_hash = ""
            folders[document.workspace_folder_id] = document.organization_id
        for folder_id, organization_id in folders.items():
            jobs.append(
                service.enqueue_system(
                    scope=OrganizationScope(organization_id),
                    workspace_folder_id=folder_id,
                ).id
            )
    return len(documents), jobs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", action="append", required=True, type=UUID)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    with build_session_factory(build_engine(settings))() as session:
        count, jobs = requeue(session, folder_ids=args.folder, settings=settings, apply=args.apply)
        if args.apply:
            session.commit()
        print(f"{'apply' if args.apply else 'dry-run'}: {count} documents; {len(jobs)} jobs")
    if jobs:
        from app.ingestion.dispatch import CeleryIngestionDispatcher
        from app.ingestion.tasks import create_celery_app

        dispatcher = CeleryIngestionDispatcher(create_celery_app(settings))
        for job_id in jobs:
            dispatcher.dispatch(job_id=job_id)


if __name__ == "__main__":
    main()
