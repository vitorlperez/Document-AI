"""Idempotent ingestion orchestration, independent of a specific source provider."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit_usage.service import ACTIVE_DOCUMENT_LIMIT, UsageLimitExceeded, UsageService
from app.core.scoping import OrganizationScope
from app.ingestion.models import ProcessingJob, ProcessingJobStatus
from app.knowledge.models import Document, DocumentChunk
from app.organizations.models import Membership, MembershipRole, Organization
from app.workspaces.models import WorkspaceFolder

PROCESSING_VERSION = "v1"
JOB_LEASE = timedelta(minutes=20)
ELIGIBLE_MIME_TYPES = {
    "application/vnd.google-apps.document",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class SyncAccessDenied(PermissionError):
    pass


@dataclass(frozen=True)
class DiscoveredDocument:
    """Extracted content returned by an authorized source adapter."""

    external_file_id: str
    name: str
    mime_type: str
    source_url: str
    modified_at: datetime | None = None
    text: str | None = None
    page_number: int | None = None
    error_code: str | None = None
    parent_ids: tuple[str, ...] = ()


class IngestionService:
    def __init__(self, session: Session):
        self.session = session

    def require_active_member(self, *, scope: OrganizationScope, user_id: UUID) -> None:
        membership = self.session.scalar(
            select(Membership).where(
                Membership.organization_id == scope.organization_id,
                Membership.user_id == user_id,
                Membership.is_active.is_(True),
            )
        )
        if membership is None:
            raise SyncAccessDenied("workspace access denied")

    def require_admin(self, *, scope: OrganizationScope, user_id: UUID) -> None:
        membership = self.session.scalar(
            select(Membership).where(
                Membership.organization_id == scope.organization_id,
                Membership.user_id == user_id,
                Membership.is_active.is_(True),
                Membership.role.in_([MembershipRole.OWNER, MembershipRole.ADMIN]),
            )
        )
        if membership is None:
            raise SyncAccessDenied("sync access denied")

    def require_folder(self, *, scope: OrganizationScope, workspace_folder_id: UUID) -> WorkspaceFolder:
        folder = self.session.scalar(
            select(WorkspaceFolder).where(
                WorkspaceFolder.id == workspace_folder_id,
                WorkspaceFolder.organization_id == scope.organization_id,
            )
        )
        if folder is None:
            raise SyncAccessDenied("workspace access denied")
        return folder

    def enqueue(self, *, scope: OrganizationScope, user_id: UUID, workspace_folder_id: UUID) -> ProcessingJob:
        self.require_admin(scope=scope, user_id=user_id)
        folder = self.require_folder(scope=scope, workspace_folder_id=workspace_folder_id)
        active_job = self.session.scalar(
            select(ProcessingJob).where(
                ProcessingJob.organization_id == scope.organization_id,
                ProcessingJob.workspace_folder_id == workspace_folder_id,
                ProcessingJob.status.in_([ProcessingJobStatus.QUEUED, ProcessingJobStatus.SYNCING]),
            )
        )
        if active_job is not None:
            return active_job

        job = ProcessingJob(
            organization_id=scope.organization_id,
            workspace_folder_id=workspace_folder_id,
            idempotency_key=sha256(f"{scope.organization_id}:{workspace_folder_id}:{uuid4()}".encode()).hexdigest(),
            status=ProcessingJobStatus.QUEUED,
        )
        try:
            # The PostgreSQL partial unique index is the final concurrency gate.
            # A savepoint lets the losing request refetch the committed winner.
            with self.session.begin_nested():
                self.session.add(job)
                self.session.flush()
        except IntegrityError:
            active_job = self.session.scalar(
                select(ProcessingJob).where(
                    ProcessingJob.organization_id == scope.organization_id,
                    ProcessingJob.workspace_folder_id == workspace_folder_id,
                    ProcessingJob.status.in_([ProcessingJobStatus.QUEUED, ProcessingJobStatus.SYNCING]),
                )
            )
            if active_job is not None:
                return active_job
            raise
        if not self._has_indexed_documents(folder):
            folder.status = ProcessingJobStatus.QUEUED.value
        return job

    def indexed_documents(
        self, *, scope: OrganizationScope, user_id: UUID, workspace_folder_id: UUID
    ) -> list[Document]:
        self.require_active_member(scope=scope, user_id=user_id)
        self.require_folder(scope=scope, workspace_folder_id=workspace_folder_id)
        return list(
            self.session.scalars(
                select(Document)
                .where(
                    Document.organization_id == scope.organization_id,
                    Document.workspace_folder_id == workspace_folder_id,
                    Document.index_status == "indexed",
                )
                .order_by(Document.name, Document.id)
            )
        )

    def claim(self, *, job_id: UUID) -> ProcessingJob | None:
        """Atomically reserve a queued or abandoned job for one worker."""
        started_at = datetime.now(UTC)
        run_token = uuid4().hex
        result = self.session.execute(
            update(ProcessingJob)
            .where(
                ProcessingJob.id == job_id,
                (
                    (ProcessingJob.status == ProcessingJobStatus.QUEUED)
                    | (
                        (ProcessingJob.status == ProcessingJobStatus.SYNCING)
                        & (ProcessingJob.started_at < started_at - JOB_LEASE)
                    )
                ),
            )
            .execution_options(synchronize_session=False)
            .values(
                status=ProcessingJobStatus.SYNCING,
                started_at=started_at,
                completed_at=None,
                error_code=None,
                run_token=run_token,
            )
        )
        if result.rowcount != 1:
            return None
        job = self.session.scalar(
            select(ProcessingJob)
            .where(ProcessingJob.id == job_id, ProcessingJob.run_token == run_token)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if job is None:
            return None
        folder = self._folder_for_job(job)
        if not self._has_indexed_documents(folder):
            folder.status = ProcessingJobStatus.SYNCING.value
        self.session.flush()
        return job

    def reconcile(self, *, job_id: UUID, documents: list[DiscoveredDocument]) -> ProcessingJob | None:
        """Apply one successful full reconciliation.

        A source failure must call :meth:`fail` instead: only this completed
        reconciliation is allowed to remove documents no longer in scope.
        """
        job = self.claim(job_id=job_id)
        if job is None:
            return None
        return self.apply_reconciliation(job_id=job.id, run_token=job.run_token, documents=documents)

    def apply_reconciliation(
        self, *, job_id: UUID, run_token: str | None, documents: list[DiscoveredDocument], finalize: bool = True
    ) -> ProcessingJob | None:
        """Persist a discovered snapshot only while this worker owns the job."""
        if run_token is None:
            return None
        job = self._owned_running_job(job_id=job_id, run_token=run_token)
        if job is None:
            return None
        now = datetime.now(UTC)
        seen_file_ids = {document.external_file_id for document in documents}
        # Reconciliation is a complete snapshot. Free capacity from files that
        # left the selected folder before deciding whether incoming files may
        # become active indexed documents.
        missing_documents = self.session.scalars(
            select(Document).where(
                Document.organization_id == job.organization_id,
                Document.workspace_folder_id == job.workspace_folder_id,
                Document.external_file_id.not_in(seen_file_ids) if seen_file_ids else True,
            )
        )
        for document in missing_documents:
            document.index_status = "removed"
            document.error_code = None

        failures = 0
        for discovered in documents:
            if discovered.mime_type not in ELIGIBLE_MIME_TYPES:
                self._upsert_nonindexed(job, discovered, status="ignored", error_code="unsupported_file_type")
                continue
            if discovered.error_code or not discovered.text or not discovered.text.strip():
                self._upsert_nonindexed(
                    job,
                    discovered,
                    status="failed",
                    error_code=discovered.error_code or "empty_extracted_text",
                )
                failures += 1
                continue
            self._upsert_indexed(job, discovered, indexed_at=now)

        if finalize:
            return self.finalize_reconciliation(
                job_id=job.id,
                run_token=run_token,
                partial_failure=failures > 0,
                completed_at=now,
            )
        self.session.flush()
        return job

    def finalize_reconciliation(
        self,
        *,
        job_id: UUID,
        run_token: str | None,
        partial_failure: bool,
        completed_at: datetime | None = None,
    ) -> ProcessingJob | None:
        """Expose a completed snapshot only after every ingestion stage succeeds."""
        if run_token is None:
            return None
        job = self._owned_running_job(job_id=job_id, run_token=run_token)
        if job is None:
            return None
        final_time = completed_at or datetime.now(UTC)
        job.status = ProcessingJobStatus.PARTIAL_FAILURE if partial_failure else ProcessingJobStatus.READY
        job.completed_at = final_time
        job.error_code = None
        folder = self._folder_for_job(job)
        folder.status = job.status.value
        folder.last_synced_at = final_time
        self.session.flush()
        return job

    def complete(self, *, job_id: UUID, partial_failure: bool = False) -> ProcessingJob | None:
        job = self._load_job(job_id)
        if job.status in {ProcessingJobStatus.READY, ProcessingJobStatus.PARTIAL_FAILURE, ProcessingJobStatus.FAILED}:
            return None
        completed_at = datetime.now(UTC)
        job.status = ProcessingJobStatus.PARTIAL_FAILURE if partial_failure else ProcessingJobStatus.READY
        job.completed_at = completed_at
        folder = self._folder_for_job(job)
        folder.status = job.status.value
        folder.last_synced_at = completed_at
        self.session.flush()
        return job

    def fail(
        self, *, job_id: UUID, error_code: str, expected_run_token: str | None = None
    ) -> ProcessingJob | None:
        if expected_run_token is None:
            job = self._load_job(job_id)
            if job.status != ProcessingJobStatus.QUEUED:
                return None
        else:
            job = self._owned_running_job(job_id=job_id, run_token=expected_run_token)
        if job is None:
            return None
        job.status = ProcessingJobStatus.FAILED
        job.error_code = error_code
        job.completed_at = datetime.now(UTC)
        folder = self._folder_for_job(job)
        # A failed remote reconciliation never replaces a complete snapshot.
        # Keep that snapshot searchable while surfacing the failed job itself.
        folder.status = (
            ProcessingJobStatus.PARTIAL_FAILURE.value
            if self._has_indexed_documents(folder)
            else ProcessingJobStatus.FAILED.value
        )
        self.session.flush()
        return job

    def release_for_retry(self, *, job_id: UUID, expected_run_token: str) -> ProcessingJob | None:
        job = self._owned_running_job(job_id=job_id, run_token=expected_run_token)
        if job is None:
            return None
        job.status = ProcessingJobStatus.QUEUED
        job.error_code = None
        folder = self._folder_for_job(job)
        if not self._has_indexed_documents(folder):
            folder.status = ProcessingJobStatus.QUEUED.value
        self.session.flush()
        return job

    def _has_indexed_documents(self, folder: WorkspaceFolder) -> bool:
        return self.session.scalar(
            select(Document.id)
            .where(
                Document.organization_id == folder.organization_id,
                Document.workspace_folder_id == folder.id,
                Document.index_status == "indexed",
            )
            .limit(1)
        ) is not None

    def nonindexed_documents(
        self, *, scope: OrganizationScope, user_id: UUID, workspace_folder_id: UUID
    ) -> list[Document]:
        self.require_admin(scope=scope, user_id=user_id)
        self.require_folder(scope=scope, workspace_folder_id=workspace_folder_id)
        return list(
            self.session.scalars(
                select(Document)
                .where(
                    Document.organization_id == scope.organization_id,
                    Document.workspace_folder_id == workspace_folder_id,
                    Document.index_status.in_(["failed", "ignored"]),
                )
                .order_by(Document.name, Document.id)
            )
        )

    def support_failure_summary(self, *, scope: OrganizationScope) -> dict[UUID, list[tuple[str, int]]]:
        """Aggregate safe failure codes for platform support without exposing files."""
        rows = self.session.execute(
            select(Document.workspace_folder_id, Document.error_code, func.count(Document.id))
            .where(
                Document.organization_id == scope.organization_id,
                Document.index_status.in_(["failed", "ignored"]),
                Document.error_code.is_not(None),
            )
            .group_by(Document.workspace_folder_id, Document.error_code)
            .order_by(Document.workspace_folder_id, Document.error_code)
        ).all()
        summary: dict[UUID, list[tuple[str, int]]] = {}
        for folder_id, error_code, count in rows:
            if error_code is not None:
                summary.setdefault(folder_id, []).append((error_code, count))
        return summary

    def _load_job(self, job_id: UUID) -> ProcessingJob:
        job = self.session.get(ProcessingJob, job_id)
        if job is None:
            raise ValueError("job not found")
        return job

    def _owned_running_job(self, *, job_id: UUID, run_token: str) -> ProcessingJob | None:
        return self.session.scalar(
            select(ProcessingJob)
            .where(
                ProcessingJob.id == job_id,
                ProcessingJob.status == ProcessingJobStatus.SYNCING,
                ProcessingJob.run_token == run_token,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )

    def _folder_for_job(self, job: ProcessingJob) -> WorkspaceFolder:
        folder = self.session.scalar(
            select(WorkspaceFolder).where(
                WorkspaceFolder.id == job.workspace_folder_id,
                WorkspaceFolder.organization_id == job.organization_id,
            )
        )
        if folder is None:
            raise ValueError("workspace folder not found")
        return folder

    def _document_for(self, job: ProcessingJob, external_file_id: str) -> Document | None:
        return self.session.scalar(
            select(Document).where(
                Document.organization_id == job.organization_id,
                Document.workspace_folder_id == job.workspace_folder_id,
                Document.external_file_id == external_file_id,
            )
        )

    def _upsert_nonindexed(
        self, job: ProcessingJob, discovered: DiscoveredDocument, *, status: str, error_code: str
    ) -> None:
        document = self._document_for(job, discovered.external_file_id)
        if document is None:
            self.session.add(
                Document(
                    organization_id=job.organization_id,
                    workspace_folder_id=job.workspace_folder_id,
                    external_file_id=discovered.external_file_id,
                    name=discovered.name,
                    mime_type=discovered.mime_type,
                    source_url=discovered.source_url,
                    content_hash="",
                    modified_at=discovered.modified_at,
                    processing_version=PROCESSING_VERSION,
                    index_status=status,
                    error_code=error_code,
                )
            )
            return
        document.name = discovered.name
        document.mime_type = discovered.mime_type
        document.source_url = discovered.source_url
        document.modified_at = discovered.modified_at
        document.index_status = status
        document.error_code = error_code

    def _upsert_indexed(self, job: ProcessingJob, discovered: DiscoveredDocument, *, indexed_at: datetime) -> None:
        assert discovered.text is not None
        content_hash = sha256(discovered.text.encode()).hexdigest()
        document = self._document_for(job, discovered.external_file_id)
        if document is None:
            self._require_active_document_capacity(organization_id=job.organization_id)
            UsageService(self.session).check_and_record(
                scope=OrganizationScope(job.organization_id), metric="processed_bytes", increment=len(discovered.text.encode())
            )
            document = Document(
                organization_id=job.organization_id,
                workspace_folder_id=job.workspace_folder_id,
                external_file_id=discovered.external_file_id,
                name=discovered.name,
                mime_type=discovered.mime_type,
                source_url=discovered.source_url,
                content_hash=content_hash,
                modified_at=discovered.modified_at,
                indexed_at=indexed_at,
                processing_version=PROCESSING_VERSION,
                index_status="indexed",
            )
            self.session.add(document)
            self.session.flush()
        else:
            unchanged = (
                document.content_hash == content_hash
                and document.processing_version == PROCESSING_VERSION
                and document.index_status == "indexed"
            )
            if unchanged:
                document.name = discovered.name
                document.mime_type = discovered.mime_type
                document.source_url = discovered.source_url
                document.modified_at = discovered.modified_at
                return
            if document.index_status != "indexed":
                self._require_active_document_capacity(organization_id=job.organization_id)
            UsageService(self.session).check_and_record(
                scope=OrganizationScope(job.organization_id), metric="processed_bytes", increment=len(discovered.text.encode())
            )
            document.name = discovered.name
            document.mime_type = discovered.mime_type
            document.source_url = discovered.source_url
            document.modified_at = discovered.modified_at
            document.index_status = "indexed"
            document.error_code = None
            document.content_hash = content_hash
            document.indexed_at = indexed_at
            document.processing_version = PROCESSING_VERSION
            self.session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
            self.session.flush()

        for position, text in enumerate(_chunk_text(discovered.text)):
            self.session.add(
                DocumentChunk(
                    organization_id=job.organization_id,
                    workspace_folder_id=job.workspace_folder_id,
                    document_id=document.id,
                    position=position,
                    text=text,
                    search_text=f"{discovered.name}\n{text}",
                    page_number=discovered.page_number,
                )
            )

    def _require_active_document_capacity(self, *, organization_id: UUID) -> None:
        # A row lock serializes capacity decisions from concurrent folder jobs
        # in the same tenant. PostgreSQL then sees each committed active count.
        organization = self.session.scalar(
            select(Organization).where(Organization.id == organization_id).with_for_update()
        )
        if organization is None:
            raise ValueError("organization not found")
        active_count = self.session.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.organization_id == organization_id, Document.index_status == "indexed")
        )
        if active_count is not None and active_count >= ACTIVE_DOCUMENT_LIMIT:
            raise UsageLimitExceeded("organization active document limit reached")


def _chunk_text(text: str, *, chunk_size: int = 1200) -> list[str]:
    normalized = " ".join(text.split())
    return [normalized[start : start + chunk_size] for start in range(0, len(normalized), chunk_size)]
