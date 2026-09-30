"""Worker entry point; run with ``celery -A app.ingestion.tasks worker``."""

import logging
import os
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from celery import Celery
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_usage.service import UsageLimitExceeded
from app.core.config import Settings, get_settings
from app.core.database import build_engine, build_session_factory
from app.core.scoping import OrganizationScope
from app.ingestion.extraction import eligible_mime_types
from app.ingestion.extraction.mime import normalize_mime_type
from app.ingestion.models import ProcessingJob, ProcessingJobStatus
from app.ingestion.service import DiscoveryResult, IngestionService
from app.integrations.errors import SourceRemoteUnauthorized
from app.integrations.http import RemoteThrottled
from app.integrations.models import DataSource
from app.ingestion.extraction.cache import purge_cache
from app.integrations.registry import IntegrationRegistry
from app.knowledge.models import Document
from app.knowledge.questions import AIProviderUnavailable, EmbeddingService, OpenAIQuestionProvider
from app.library.service import LibraryService
from app.workspaces.models import WorkspaceFolder, WorkspaceFolderSelection

logger = logging.getLogger("document_intelligence.ingestion")
celery_app = Celery(
    "document_intelligence", broker=os.getenv("REDIS_URL", "redis://localhost:6379/0")
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_transport_options={"visibility_timeout": 1800},
)


TERMINAL_ERROR_CODES = frozenset({"file_encrypted", "file_too_large", "ocr_document_too_large"})


def create_celery_app(settings: Settings) -> Celery:
    celery_app.conf.broker_url = settings.redis_url
    celery_app.conf.beat_schedule = {
        "schedule-connected-source-reconciliation": {
            "task": "document_intelligence.ingestion.schedule",
            "schedule": timedelta(minutes=settings.sync_scheduler_interval_minutes),
        },
        "purge-extraction-cache": {
            "task": "document_intelligence.ingestion.purge_extraction_cache",
            "schedule": timedelta(days=1),
        },
    }
    return celery_app


def schedule_connected_source_reconciliations(
    *,
    session: Session,
    settings: Settings,
    send_task: Callable[..., object],
    now: datetime | None = None,
) -> dict[str, int]:
    """Queue stale connected sources while preserving the normal job lifecycle."""
    current_time = now or datetime.now(UTC)
    freshness_cutoff = current_time - timedelta(hours=settings.sync_freshness_hours)
    failure_cutoff = current_time - timedelta(
        minutes=settings.sync_scheduler_failure_cooldown_minutes
    )
    slo_cutoff = freshness_cutoff - timedelta(hours=settings.sync_scheduler_slo_grace_hours)
    sources = list(
        session.scalars(
            select(DataSource)
            .where(DataSource.status == "connected")
            .order_by(DataSource.organization_id, DataSource.id)
        )
    )
    sources_by_id = {source.id: source for source in sources}
    folders = list(
        session.scalars(
            select(WorkspaceFolder)
            .join(DataSource, WorkspaceFolder.source_id == DataSource.id)
            .where(DataSource.status == "connected")
            .order_by(WorkspaceFolder.organization_id, WorkspaceFolder.source_id, WorkspaceFolder.id)
        )
    )
    counts = {"considered": len(folders), "enqueued": 0, "skipped": 0}
    enqueued_per_organization: dict[UUID, int] = {}
    jobs_to_dispatch: list[UUID] = []

    for source in sources:
        last_synced_at = _as_utc(source.last_synced_at)
        if last_synced_at is None or last_synced_at < slo_cutoff:
            logger.warning(
                "connected source exceeds sync freshness SLO",
                extra={
                    "event": "ingestion_scheduler_slo_exceeded",
                    "source_id": str(source.id),
                    "organization_id": str(source.organization_id),
                    "last_synced_at": source.last_synced_at.isoformat()
                    if source.last_synced_at
                    else None,
                },
            )

    ocr_backlog = set(
        session.scalars(
            select(Document.workspace_folder_id)
            .where(Document.index_status == "failed", Document.error_code == "ocr_budget_exceeded")
            .distinct()
        )
    )
    for folder in folders:
        source = sources_by_id[folder.source_id]
        last_synced_at = _as_utc(source.last_synced_at)
        if (
            last_synced_at is not None
            and last_synced_at >= freshness_cutoff
            and folder.id not in ocr_backlog
        ):
            counts["skipped"] += 1
            continue
        if (
            enqueued_per_organization.get(folder.organization_id, 0)
            >= settings.sync_scheduler_max_concurrent_per_org
        ):
            counts["skipped"] += 1
            continue
        active_job = session.scalar(
            select(ProcessingJob.id).where(
                ProcessingJob.organization_id == folder.organization_id,
                ProcessingJob.workspace_folder_id == folder.id,
                ProcessingJob.status.in_(
                    [ProcessingJobStatus.QUEUED, ProcessingJobStatus.SYNCING]
                ),
            )
        )
        if active_job is not None:
            counts["skipped"] += 1
            continue
        latest_failure = session.scalar(
            select(ProcessingJob)
            .where(
                ProcessingJob.organization_id == folder.organization_id,
                ProcessingJob.workspace_folder_id == folder.id,
                ProcessingJob.status == ProcessingJobStatus.FAILED,
            )
            .order_by(ProcessingJob.completed_at.desc(), ProcessingJob.created_at.desc())
            .limit(1)
        )
        failure_at = (
            _as_utc(latest_failure.completed_at or latest_failure.created_at)
            if latest_failure
            else None
        )
        if failure_at is not None and failure_at >= failure_cutoff:
            counts["skipped"] += 1
            continue
        job = IngestionService(session).enqueue_system(
            scope=OrganizationScope(folder.organization_id),
            workspace_folder_id=folder.id,
        )
        jobs_to_dispatch.append(job.id)
        enqueued_per_organization[folder.organization_id] = (
            enqueued_per_organization.get(folder.organization_id, 0) + 1
        )
        counts["enqueued"] += 1

    session.commit()
    for position, job_id in enumerate(jobs_to_dispatch):
        send_task(
            "document_intelligence.ingestion.reconcile",
            args=[str(job_id)],
            countdown=position * 5,
        )
    logger.info(
        "periodic ingestion scheduling complete",
        extra={"event": "ingestion_scheduler", **counts},
    )
    return counts


def _as_utc(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


@celery_app.task(name="document_intelligence.ingestion.schedule")
def schedule_periodic_reconciliation() -> dict[str, int]:
    settings = get_settings()
    session_factory = build_session_factory(build_engine(settings))
    with session_factory() as session:
        return schedule_connected_source_reconciliations(
            session=session,
            settings=settings,
            send_task=celery_app.send_task,
        )


@celery_app.task(name="document_intelligence.ingestion.purge_extraction_cache")
def purge_extraction_cache_task() -> int:
    session_factory = build_session_factory(build_engine(get_settings()))
    with session_factory() as session:
        removed = purge_cache(session)
        session.commit()
        return removed


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
        service.settings = settings
        service.eligible_mime_types = eligible_mime_types(settings)
        source_provider = "unknown"
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
                service.fail(
                    job_id=job.id,
                    error_code="workspace_folder_not_found",
                    expected_run_token=run_token,
                )
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
                service.fail(
                    job_id=job.id, error_code="source_not_connected", expected_run_token=run_token
                )
                session.commit()
                return
            source_provider = getattr(source, "provider", "google_drive")
            provider = IntegrationRegistry(settings).get(
                source_provider,
                session=session,
                source_id=source.id,
                organization_id=job.organization_id,
                session_factory=session_factory,
            )
            provider.eligible_mime_types = eligible_mime_types(settings)
            selections = list(
                session.scalars(
                    select(WorkspaceFolderSelection)
                    .where(WorkspaceFolderSelection.workspace_folder_id == folder.id)
                    .order_by(
                        WorkspaceFolderSelection.kind, WorkspaceFolderSelection.external_folder_id
                    )
                )
            )
            if not selections:
                service.fail(
                    job_id=job.id,
                    error_code="workspace_scope_not_found",
                    expected_run_token=run_token,
                )
                session.commit()
                return
            known_rows = list(
                session.scalars(
                    select(Document).where(
                        Document.organization_id == job.organization_id,
                        Document.workspace_folder_id == job.workspace_folder_id,
                    )
                )
            )
            force_file_ids = {
                document.external_file_id
                for document in known_rows
                if (document.index_status == "failed" and getattr(document, "error_code", None) not in TERMINAL_ERROR_CODES)
                or (document.index_status == "indexed" and document.content_hash == "")
                or (document.index_status == "ignored"
                    and document.error_code == "unsupported_file_type"
                    and normalize_mime_type(document.name, document.mime_type) in eligible_mime_types(settings))
            }
            discover_kwargs = {
                "encrypted_credentials": source.encrypted_credentials,
                "selections": selections,
                "force_file_ids": force_file_ids,
            }
            discover_kwargs["known_documents"] = {
                document.external_file_id: (document.modified_at, document.index_status)
                for document in known_rows
            }
            if getattr(job, "manual_run_id", None):
                discover_kwargs["force_full"] = True
            discovered_documents = provider.discover(**discover_kwargs)
            discovery = (
                discovered_documents if isinstance(discovered_documents, DiscoveryResult) else None
            )
            document_results = discovery.documents if discovery else discovered_documents
            # Keep remote metadata and the document snapshot in the same unit
            # of work. A failed projection retries the job and never leaves a
            # ready sync that cannot be browsed from the Company Library.
            folders_for = getattr(provider, "folders_for_selections", None)
            source_folders = (
                folders_for(
                    encrypted_credentials=source.encrypted_credentials, selections=selections
                )
                if folders_for
                else provider.folders(encrypted_credentials=source.encrypted_credentials)
            )
            document_results, source_folders = LibraryService(session).filter_excluded_content(
                organization_id=job.organization_id, source_id=source.id,
                documents=document_results, folders=source_folders,
            )
            discovered_documents = (
                replace(discovery, documents=document_results) if discovery else document_results
            )
            if getattr(job, "manual_run_id", None):
                from app.library.manual_sync import scoped_documents, update_progress
                manual_documents = scoped_documents(session, job, document_results, source_folders)
                update_progress(session, job, total=len(manual_documents), outcomes=[
                    {"external_id": item.external_file_id, "name": item.name, "processed": False,
                     "error_code": None} for item in manual_documents])
                session.commit()
            session.refresh(source)
            if source.status != "connected":
                service.fail(
                    job_id=job.id, error_code="source_not_connected", expected_run_token=run_token
                )
                session.commit()
                return
            projected_job = service.apply_reconciliation(
                job_id=job.id,
                run_token=run_token,
                documents=discovered_documents,
                manual_folders=source_folders,
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
                service.fail(
                    job_id=job.id, error_code="source_not_connected", expected_run_token=run_token
                )
                session.commit()
                return
            completed_job = service.finalize_reconciliation(
                job_id=job.id,
                run_token=run_token,
                partial_failure=service.has_failed_documents(
                    organization_id=job.organization_id,
                    workspace_folder_id=job.workspace_folder_id,
                ),
            )
            if completed_job is None:
                session.rollback()
                return
            LibraryService(session).project_successful_sync(
                organization_id=job.organization_id,
                source=source,
                documents=document_results,
                folders=source_folders,
            )
            if discovery and discovery.delta_links is not None:
                selections_by_id = {item.id: item for item in selections}
                encrypt_delta_link = getattr(provider, "encrypt_delta_link", None)
                for selection_id, cursor in discovery.delta_links.items():
                    selection = selections_by_id.get(selection_id)
                    if selection is not None:
                        selection.encrypted_delta_link = (
                            encrypt_delta_link(cursor)
                            if cursor and encrypt_delta_link
                            else None
                        )
            updated_credentials = getattr(provider, "updated_encrypted_credentials", None)
            if updated_credentials:
                source.encrypted_credentials = updated_credentials
            source.last_synced_at = completed_job.completed_at
            session.commit()
            logger.info(
                "workspace reconciliation complete",
                extra={
                    "event": "ingestion_sync",
                    "result": "complete",
                    "provider": source_provider,
                    "action": "reconcile",
                    "job_id": job_id,
                },
            )
        except SourceRemoteUnauthorized:
            if source is not None:
                source.status = "reauth_required"
            if run_token is not None:
                service.fail(
                    job_id=UUID(job_id),
                    error_code="source_reauth_required",
                    expected_run_token=run_token,
                )
            session.commit()
            logger.warning(
                "workspace reconciliation requires authorization",
                extra={
                    "event": "ingestion_sync",
                    "result": "reauth_required",
                    "reason": "remote_401_or_403",
                    "provider": source_provider,
                    "action": "reconcile",
                    "job_id": job_id,
                },
            )
        except AIProviderUnavailable:
            if run_token is None:
                raise
            # The new reconciliation has not committed. Roll it back before
            # surfacing a safe status, so the prior indexed snapshot remains searchable.
            session.rollback()
            if self.request.retries >= self.max_retries:
                service.fail(
                    job_id=UUID(job_id), error_code="embedding_failed", expected_run_token=run_token
                )
                session.commit()
                logger.warning(
                    "workspace embedding failed",
                    extra={
                        "event": "ingestion_embedding",
                        "result": "failed",
                        "action": "embed",
                        "job_id": job_id,
                    },
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
            service.fail(
                job_id=UUID(job_id), error_code="usage_limit_exceeded", expected_run_token=run_token
            )
            session.commit()
            logger.warning(
                "workspace reconciliation exceeded its organization usage limit",
                extra={
                    "event": "ingestion_sync",
                    "result": "usage_limit_exceeded",
                    "provider": source_provider,
                    "action": "reconcile",
                    "job_id": job_id,
                },
            )
        except RemoteThrottled as error:
            session.rollback()
            if run_token is None:
                raise
            exhausted = self.request.retries >= self.max_retries
            if exhausted:
                service.fail(job_id=UUID(job_id), error_code="source_rate_limited", expected_run_token=run_token)
            else:
                service.release_for_retry(job_id=UUID(job_id), expected_run_token=run_token)
            session.commit()
            logger.warning("remote source rate limited", extra={"event": "ingestion_sync", "result": "rate_limited", "provider": source_provider, "job_id": job_id})
            if exhausted:
                return
            raise self.retry(countdown=max(error.retry_after_seconds or 0, 30 * (2 ** self.request.retries)))
        except Exception as error:
            session.rollback()
            if run_token is None:
                raise
            if self.request.retries >= self.max_retries:
                service.fail(
                    job_id=UUID(job_id), error_code="sync_failed", expected_run_token=run_token
                )
                session.commit()
                logger.warning(
                    "workspace reconciliation failed",
                    extra={
                        "event": "ingestion_sync",
                        "result": "failed",
                        "provider": source_provider,
                        "action": "reconcile",
                        "job_id": job_id,
                    },
                )
                return
            service.release_for_retry(job_id=UUID(job_id), expected_run_token=run_token)
            session.commit()
            raise self.retry(exc=error, countdown=10 * (2**self.request.retries)) from error
