"""Worker entry point; run with ``celery -A app.ingestion.tasks worker``."""

import logging
import os
from uuid import UUID

from celery import Celery
from sqlalchemy import select

from app.audit_usage.service import UsageLimitExceeded
from app.core.config import Settings, get_settings
from app.core.database import build_engine, build_session_factory
from app.core.scoping import OrganizationScope
from app.ingestion.google_drive import GoogleDriveDocumentProvider
from app.ingestion.service import ELIGIBLE_MIME_TYPES, IngestionService
from app.integrations.google_drive import (
    CredentialCipher,
    GoogleDriveOAuthClient,
    GoogleRemoteUnauthorized,
)
from app.integrations.models import DataSource
from app.knowledge.questions import AIProviderUnavailable, EmbeddingService, OpenAIQuestionProvider
from app.library.service import LibraryService
from app.workspaces.models import WorkspaceFolder, WorkspaceFolderSelection

logger = logging.getLogger("document_intelligence.ingestion")
celery_app = Celery("document_intelligence", broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"))
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_transport_options={"visibility_timeout": 1800},
)


def create_celery_app(settings: Settings) -> Celery:
    celery_app.conf.broker_url = settings.redis_url
    return celery_app


@celery_app.task(
    bind=True,
    name="document_intelligence.ingestion.reconcile",
    max_retries=3,
    default_retry_delay=10,
)
def reconcile_workspace_folder(self, job_id: str) -> None:  # type: ignore[no-untyped-def]
    settings = get_settings()
    session_factory = build_session_factory(build_engine(settings))
    with session_factory() as session:
        service = IngestionService(session)
        source: DataSource | None = None
        run_token: str | None = None
        try:
            job = service.claim(job_id=UUID(job_id))
            if job is None:
                return
            run_token = job.run_token
            if run_token is None:
                return
            # Do not retain a database transaction or row lock while reading a
            # remote folder. A duplicate delivery will see the fresh lease.
            session.commit()
            folder = session.scalar(
                select(WorkspaceFolder).where(
                    WorkspaceFolder.id == job.workspace_folder_id,
                    WorkspaceFolder.organization_id == job.organization_id,
                )
            )
            if folder is None:
                service.fail(job_id=job.id, error_code="workspace_folder_not_found", expected_run_token=run_token)
                session.commit()
                return
            source = session.scalar(
                select(DataSource).where(
                    DataSource.id == folder.source_id,
                    DataSource.organization_id == job.organization_id,
                    DataSource.status == "connected",
                )
            )
            if source is None:
                service.fail(job_id=job.id, error_code="source_not_connected", expected_run_token=run_token)
                session.commit()
                return
            provider = GoogleDriveDocumentProvider(
                GoogleDriveOAuthClient(
                    client_id=settings.google_oauth_client_id,
                    client_secret=(
                        settings.google_oauth_client_secret.get_secret_value()
                        if settings.google_oauth_client_secret
                        else None
                    ),
                    redirect_uri=settings.google_oauth_redirect_uri,
                ),
                CredentialCipher(
                    settings.google_token_encryption_key.get_secret_value()
                    if settings.google_token_encryption_key
                    else None
                ),
            )
            selections = list(
                session.scalars(
                    select(WorkspaceFolderSelection)
                    .where(WorkspaceFolderSelection.workspace_folder_id == folder.id)
                    .order_by(WorkspaceFolderSelection.kind, WorkspaceFolderSelection.external_folder_id)
                )
            )
            if not selections:
                service.fail(job_id=job.id, error_code="workspace_scope_not_found", expected_run_token=run_token)
                session.commit()
                return
            discovered_documents = provider.discover(
                encrypted_credentials=source.encrypted_credentials,
                selections=selections,
            )
            # Keep remote metadata and the document snapshot in the same unit
            # of work. A failed projection retries the job and never leaves a
            # ready sync that cannot be browsed from the Company Library.
            source_folders = provider.folders(encrypted_credentials=source.encrypted_credentials)
            session.refresh(source)
            if source.status != "connected":
                service.fail(job_id=job.id, error_code="source_not_connected", expected_run_token=run_token)
                session.commit()
                return
            projected_job = service.apply_reconciliation(
                job_id=job.id,
                run_token=run_token,
                documents=discovered_documents,
                finalize=False,
            )
            if projected_job is None:
                session.rollback()
                return
            EmbeddingService(
                session,
                OpenAIQuestionProvider(
                    settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
                ),
            ).embed_workspace(
                scope=OrganizationScope(job.organization_id),
                workspace_folder_id=job.workspace_folder_id,
            )
            session.refresh(source)
            if source.status != "connected":
                session.rollback()
                service.fail(job_id=job.id, error_code="source_not_connected", expected_run_token=run_token)
                session.commit()
                return
            completed_job = service.finalize_reconciliation(
                job_id=job.id,
                run_token=run_token,
                partial_failure=any(
                    document.mime_type in ELIGIBLE_MIME_TYPES
                    and (document.error_code is not None or not document.text or not document.text.strip())
                    for document in discovered_documents
                ),
            )
            if completed_job is None:
                session.rollback()
                return
            LibraryService(session).project_successful_sync(
                organization_id=job.organization_id,
                source=source,
                documents=discovered_documents,
                folders=source_folders,
            )
            source.last_synced_at = completed_job.completed_at
            session.commit()
            logger.info(
                "workspace reconciliation complete",
                extra={"event": "ingestion_sync", "result": "complete", "provider": "google_drive", "action": "reconcile", "job_id": job_id},
            )
        except GoogleRemoteUnauthorized:
            if source is not None:
                source.status = "reauth_required"
            if run_token is not None:
                service.fail(job_id=UUID(job_id), error_code="source_reauth_required", expected_run_token=run_token)
            session.commit()
            logger.warning(
                "workspace reconciliation requires authorization",
                extra={"event": "ingestion_sync", "result": "reauth_required", "provider": "google_drive", "action": "reconcile", "job_id": job_id},
            )
        except AIProviderUnavailable:
            if run_token is None:
                raise
            # The new reconciliation has not committed. Roll it back before
            # surfacing a safe status, so the prior indexed snapshot remains searchable.
            session.rollback()
            if self.request.retries >= self.max_retries:
                service.fail(job_id=UUID(job_id), error_code="embedding_failed", expected_run_token=run_token)
                session.commit()
                logger.warning(
                    "workspace embedding failed",
                    extra={"event": "ingestion_embedding", "result": "failed", "action": "embed", "job_id": job_id},
                )
                return
            service.release_for_retry(job_id=UUID(job_id), expected_run_token=run_token)
            session.commit()
            raise self.retry(countdown=10 * (2**self.request.retries))
        except UsageLimitExceeded:
            if run_token is None:
                raise
            # A limit check may follow a usage-record write. Discard every
            # uncommitted side effect before recording the terminal job state.
            session.rollback()
            service.fail(job_id=UUID(job_id), error_code="usage_limit_exceeded", expected_run_token=run_token)
            session.commit()
            logger.warning(
                "workspace reconciliation exceeded its organization usage limit",
                extra={"event": "ingestion_sync", "result": "usage_limit_exceeded", "provider": "google_drive", "action": "reconcile", "job_id": job_id},
            )
        except Exception as error:
            session.rollback()
            if run_token is None:
                raise
            if self.request.retries >= self.max_retries:
                service.fail(job_id=UUID(job_id), error_code="sync_failed", expected_run_token=run_token)
                session.commit()
                logger.warning(
                    "workspace reconciliation failed",
                    extra={"event": "ingestion_sync", "result": "failed", "provider": "google_drive", "action": "reconcile", "job_id": job_id},
                )
                return
            service.release_for_retry(job_id=UUID(job_id), expected_run_token=run_token)
            session.commit()
            raise self.retry(exc=error, countdown=10 * (2**self.request.retries)) from error
