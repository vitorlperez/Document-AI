"""Durable lifecycle records for asynchronous folder reconciliation."""

import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class ProcessingJobStatus(str, enum.Enum):
    QUEUED = "queued"
    SYNCING = "syncing"
    READY = "ready"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


class ProcessingJob(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "processing_jobs"

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_folder_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspace_folders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[ProcessingJobStatus] = mapped_column(
        Enum(
            ProcessingJobStatus,
            name="processing_job_status",
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
        default=ProcessingJobStatus.QUEUED,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    manual_run_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("manual_sync_runs.id", ondelete="SET NULL"), index=True
    )
    run_token: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))


Index(
    "uq_active_processing_jobs_folder",
    ProcessingJob.organization_id,
    ProcessingJob.workspace_folder_id,
    unique=True,
    postgresql_where=ProcessingJob.status.in_([ProcessingJobStatus.QUEUED, ProcessingJobStatus.SYNCING]),
    sqlite_where=ProcessingJob.status.in_([ProcessingJobStatus.QUEUED, ProcessingJobStatus.SYNCING]),
)


class ExtractionCache(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Recognized page texts per tenant; client text, so same retention class as chunks."""

    __tablename__ = "extraction_cache"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "engine", "engine_version", "cache_key", name="uq_extraction_cache_key"
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    engine: Mapped[str] = mapped_column(String(40), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(40), nullable=False)
    cache_key: Mapped[str] = mapped_column(String(160), nullable=False)
    page_texts: Mapped[list[str]] = mapped_column(JSON, nullable=False)
