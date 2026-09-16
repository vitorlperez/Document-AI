from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.ingestion import document_failures, documents
from app.audit_usage.models import AuditLog, SavedQuery
from app.audit_usage.service import ACTIVE_DOCUMENT_LIMIT, UsageLimitExceeded
from app.core.models import Base
from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.ingestion.models import ProcessingJob, ProcessingJobStatus
from app.ingestion.service import (
    JOB_LEASE,
    DiscoveredDocument,
    IngestionService,
    SyncAccessDenied,
    SyncAlreadyActive,
)
from app.integrations.models import DataSource
from app.knowledge.models import Document, DocumentChunk
from app.organizations.models import Membership, MembershipRole, Organization
from app.workspaces.models import WorkspaceFolder, WorkspaceFolderSelection


@pytest.fixture()
def session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as database_session:
        yield database_session
    Base.metadata.drop_all(engine)
    engine.dispose()


def create_workspace(
    session: Session, *, role: MembershipRole = MembershipRole.ADMIN
) -> tuple[Organization, User, WorkspaceFolder]:
    organization = Organization(name="Acme")
    user = User(email="admin@example.test")
    session.add_all([organization, user])
    session.flush()
    session.add(
        Membership(
            organization_id=organization.id,
            user_id=user.id,
            role=role,
            is_active=True,
        )
    )
    source = DataSource(
        organization_id=organization.id,
        provider="google_drive",
        encrypted_credentials="ciphertext",
        status="connected",
        connected_by_user_id=user.id,
    )
    session.add(source)
    session.flush()
    folder = WorkspaceFolder(
        organization_id=organization.id,
        source_id=source.id,
        external_folder_id="folder-1",
        name="Client A",
        uniform_access_confirmed=True,
    )
    session.add(folder)
    session.commit()
    return organization, user, folder


def test_admin_enqueue_is_idempotent_for_an_active_folder_job(session: Session) -> None:
    organization, admin, folder = create_workspace(session)
    service = IngestionService(session)

    first = service.enqueue(
        scope=OrganizationScope(organization.id),
        user_id=admin.id,
        workspace_folder_id=folder.id,
    )
    second = service.enqueue(
        scope=OrganizationScope(organization.id),
        user_id=admin.id,
        workspace_folder_id=folder.id,
    )

    assert second.id == first.id
    assert first.status is ProcessingJobStatus.QUEUED
    assert folder.status == ProcessingJobStatus.QUEUED.value


def test_member_and_cross_tenant_user_cannot_enqueue_a_sync(session: Session) -> None:
    organization, member, folder = create_workspace(session, role=MembershipRole.MEMBER)
    other_organization, outsider, _ = create_workspace(session)
    service = IngestionService(session)

    with pytest.raises(SyncAccessDenied):
        service.enqueue(
            scope=OrganizationScope(organization.id),
            user_id=member.id,
            workspace_folder_id=folder.id,
        )
    with pytest.raises(SyncAccessDenied):
        service.enqueue(
            scope=OrganizationScope(other_organization.id),
            user_id=outsider.id,
            workspace_folder_id=folder.id,
        )


def test_completion_updates_job_and_folder_to_partial_failure(session: Session) -> None:
    organization, admin, folder = create_workspace(session)
    service = IngestionService(session)
    job = service.enqueue(
        scope=OrganizationScope(organization.id),
        user_id=admin.id,
        workspace_folder_id=folder.id,
    )

    completed = service.complete(job_id=job.id, partial_failure=True)

    assert completed.status is ProcessingJobStatus.PARTIAL_FAILURE
    assert completed.completed_at is not None
    assert folder.status == ProcessingJobStatus.PARTIAL_FAILURE.value
    assert folder.last_synced_at == completed.completed_at


def test_completed_sync_can_be_enqueued_again_without_reusing_a_terminal_job(session: Session) -> None:
    organization, admin, folder = create_workspace(session)
    service = IngestionService(session)
    first_job = service.enqueue(
        scope=OrganizationScope(organization.id),
        user_id=admin.id,
        workspace_folder_id=folder.id,
    )
    service.reconcile(job_id=first_job.id, documents=[])

    next_job = service.enqueue(
        scope=OrganizationScope(organization.id),
        user_id=admin.id,
        workspace_folder_id=folder.id,
    )

    assert next_job.id != first_job.id
    assert next_job.status is ProcessingJobStatus.QUEUED


def test_reconcile_upserts_documents_and_replaces_chunks_without_duplicates(session: Session) -> None:
    organization, admin, folder = create_workspace(session)
    service = IngestionService(session)
    job = service.enqueue(
        scope=OrganizationScope(organization.id),
        user_id=admin.id,
        workspace_folder_id=folder.id,
    )
    first_document = DiscoveredDocument(
        external_file_id="briefing-1",
        name="Briefing.pdf",
        mime_type="application/pdf",
        source_url="https://drive.example.test/briefing-1",
        text="The initial approved scope.",
    )

    service.reconcile(job_id=job.id, documents=[first_document])
    service.reconcile(job_id=job.id, documents=[first_document])

    document = session.scalar(select(Document).where(Document.external_file_id == "briefing-1"))
    assert document is not None
    assert session.scalar(select(func.count()).select_from(Document)) == 1
    assert session.scalar(select(func.count()).select_from(DocumentChunk)) == 1
    assert document.index_status == "indexed"
    assert session.scalar(select(DocumentChunk.text).where(DocumentChunk.document_id == document.id)) == first_document.text

    next_job = service.enqueue(
        scope=OrganizationScope(organization.id),
        user_id=admin.id,
        workspace_folder_id=folder.id,
    )
    service.reconcile(
        job_id=next_job.id,
        documents=[
            DiscoveredDocument(
                external_file_id="briefing-1",
                name="Briefing revised.pdf",
                mime_type="application/pdf",
                source_url="https://drive.example.test/briefing-1",
                text="The revised approved scope.",
            )
        ],
    )

    assert session.scalar(select(func.count()).select_from(Document)) == 1
    assert session.scalar(select(func.count()).select_from(DocumentChunk)) == 1
    assert session.scalar(select(DocumentChunk.text).where(DocumentChunk.document_id == document.id)) == "The revised approved scope."


def test_active_document_limit_is_not_monthly_and_allows_reactivation_after_capacity_is_freed(session: Session) -> None:
    organization, admin, folder = create_workspace(session)
    session.add_all(
        [
            Document(
                organization_id=organization.id,
                workspace_folder_id=folder.id,
                external_file_id=f"existing-{number}",
                name=f"Existing {number}.pdf",
                mime_type="application/pdf",
                source_url=f"https://drive.example.test/existing-{number}",
                content_hash="a" * 64,
                processing_version="v1",
                index_status="indexed",
            )
            for number in range(ACTIVE_DOCUMENT_LIMIT)
        ]
    )
    session.commit()
    service = IngestionService(session)
    snapshot = [
        DiscoveredDocument(
            external_file_id=f"existing-{number}",
            name=f"Existing {number}.pdf",
            mime_type="application/pdf",
            source_url=f"https://drive.example.test/existing-{number}",
            text=f"Current text for document {number}.",
        )
        for number in range(ACTIVE_DOCUMENT_LIMIT)
    ]
    blocked_job = service.enqueue(
        scope=OrganizationScope(organization.id), user_id=admin.id, workspace_folder_id=folder.id
    )
    with pytest.raises(UsageLimitExceeded):
        service.reconcile(
            job_id=blocked_job.id,
            documents=snapshot + [
                DiscoveredDocument(
                    external_file_id="one-too-many",
                    name="One too many.pdf",
                    mime_type="application/pdf",
                    source_url="https://drive.example.test/one-too-many",
                    text="This must not become active.",
                )
            ],
        )
    session.rollback()

    removed = session.scalar(select(Document).where(Document.external_file_id == "existing-0"))
    assert removed is not None
    removed.index_status = "removed"
    session.commit()
    reactivation_job = service.enqueue(
        scope=OrganizationScope(organization.id), user_id=admin.id, workspace_folder_id=folder.id
    )
    service.reconcile(
        job_id=reactivation_job.id,
        documents=snapshot,
    )

    assert session.scalar(
        select(func.count()).select_from(Document).where(Document.index_status == "indexed")
    ) == ACTIVE_DOCUMENT_LIMIT


def test_successful_full_reconciliation_marks_unseen_documents_removed(session: Session) -> None:
    organization, admin, folder = create_workspace(session)
    service = IngestionService(session)
    job = service.enqueue(
        scope=OrganizationScope(organization.id),
        user_id=admin.id,
        workspace_folder_id=folder.id,
    )
    service.reconcile(
        job_id=job.id,
        documents=[
            DiscoveredDocument(
                external_file_id="in-scope",
                name="In scope.pdf",
                mime_type="application/pdf",
                source_url="https://drive.example.test/in-scope",
                text="This document is initially present.",
            )
        ],
    )

    next_job = service.enqueue(
        scope=OrganizationScope(organization.id),
        user_id=admin.id,
        workspace_folder_id=folder.id,
    )
    completed = service.reconcile(job_id=next_job.id, documents=[])

    document = session.scalar(select(Document).where(Document.external_file_id == "in-scope"))
    assert document is not None
    assert document.index_status == "removed"
    assert completed.status is ProcessingJobStatus.READY
    assert folder.status == ProcessingJobStatus.READY.value


def test_source_level_failure_preserves_documents_until_a_successful_reconciliation(session: Session) -> None:
    organization, admin, folder = create_workspace(session)
    service = IngestionService(session)
    job = service.enqueue(
        scope=OrganizationScope(organization.id),
        user_id=admin.id,
        workspace_folder_id=folder.id,
    )
    service.reconcile(
        job_id=job.id,
        documents=[
            DiscoveredDocument(
                external_file_id="still-present",
                name="Still present.pdf",
                mime_type="application/pdf",
                source_url="https://drive.example.test/still-present",
                text="Do not remove this when Drive itself is unavailable.",
            )
        ],
    )
    next_job = service.enqueue(
        scope=OrganizationScope(organization.id),
        user_id=admin.id,
        workspace_folder_id=folder.id,
    )

    claim = service.claim(job_id=next_job.id)
    assert claim is not None
    failed = service.fail(
        job_id=next_job.id,
        error_code="source_unavailable",
        expected_run_token=claim.run_token,
    )

    document = session.scalar(select(Document).where(Document.external_file_id == "still-present"))
    assert document is not None
    assert document.index_status == "indexed"
    assert failed.status is ProcessingJobStatus.FAILED
    assert failed.error_code == "source_unavailable"
    assert folder.status == ProcessingJobStatus.PARTIAL_FAILURE.value


def test_document_failures_are_visible_without_failing_eligible_documents(session: Session) -> None:
    organization, admin, folder = create_workspace(session)
    service = IngestionService(session)
    job = service.enqueue(
        scope=OrganizationScope(organization.id),
        user_id=admin.id,
        workspace_folder_id=folder.id,
    )

    completed = service.reconcile(
        job_id=job.id,
        documents=[
            DiscoveredDocument(
                external_file_id="valid",
                name="Valid.pdf",
                mime_type="application/pdf",
                source_url="https://drive.example.test/valid",
                text="Valid indexed document.",
            ),
            DiscoveredDocument(
                external_file_id="failed",
                name="Failed.pdf",
                mime_type="application/pdf",
                source_url="https://drive.example.test/failed",
                error_code="text_extraction_failed",
            ),
            DiscoveredDocument(
                external_file_id="unsupported",
                name="Slides.pptx",
                mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                source_url="https://drive.example.test/unsupported",
                text="This format is unsupported in the MVP.",
            ),
        ],
    )

    rows = {row.external_file_id: row for row in session.scalars(select(Document))}
    assert completed.status is ProcessingJobStatus.PARTIAL_FAILURE
    assert folder.status == ProcessingJobStatus.PARTIAL_FAILURE.value
    assert rows["valid"].index_status == "indexed"
    assert rows["failed"].index_status == "failed"
    assert rows["failed"].error_code == "text_extraction_failed"
    assert rows["unsupported"].index_status == "ignored"
    assert rows["unsupported"].error_code == "unsupported_file_type"


def test_terminal_reconcile_is_a_noop_that_preserves_document_and_folder_state(session: Session) -> None:
    organization, admin, folder = create_workspace(session)
    service = IngestionService(session)
    job = service.enqueue(
        scope=OrganizationScope(organization.id),
        user_id=admin.id,
        workspace_folder_id=folder.id,
    )
    completed = service.reconcile(
        job_id=job.id,
        documents=[
            DiscoveredDocument(
                external_file_id="stable",
                name="Stable.pdf",
                mime_type="application/pdf",
                source_url="https://drive.example.test/stable",
                text="This must survive a duplicate worker delivery.",
            )
        ],
    )
    assert completed is not None

    duplicate = service.reconcile(job_id=job.id, documents=[])

    document = session.scalar(select(Document).where(Document.external_file_id == "stable"))
    assert duplicate is None
    assert document is not None
    assert document.index_status == "indexed"
    assert folder.status == ProcessingJobStatus.READY.value


def test_only_one_worker_can_claim_a_job_and_stale_lease_can_be_reclaimed(session: Session) -> None:
    organization, admin, folder = create_workspace(session)
    service = IngestionService(session)
    job = service.enqueue(
        scope=OrganizationScope(organization.id),
        user_id=admin.id,
        workspace_folder_id=folder.id,
    )

    first_claim = service.claim(job_id=job.id)
    duplicate_claim = service.claim(job_id=job.id)

    assert first_claim is not None
    assert first_claim.run_token is not None
    first_run_token = first_claim.run_token
    assert duplicate_claim is None
    assert folder.status == ProcessingJobStatus.SYNCING.value

    job.started_at = datetime.now(UTC) - JOB_LEASE - timedelta(seconds=1)
    session.flush()
    stale_claim = service.claim(job_id=job.id)

    assert stale_claim is not None
    assert stale_claim.started_at is not None
    assert stale_claim.run_token != first_run_token


def test_stale_worker_cannot_apply_fail_or_release_a_job_reclaimed_by_new_owner(session: Session) -> None:
    organization, admin, folder = create_workspace(session)
    service = IngestionService(session)
    job = service.enqueue(
        scope=OrganizationScope(organization.id),
        user_id=admin.id,
        workspace_folder_id=folder.id,
    )
    first_claim = service.claim(job_id=job.id)
    assert first_claim is not None
    assert first_claim.run_token is not None
    first_token = first_claim.run_token

    job.started_at = datetime.now(UTC) - JOB_LEASE - timedelta(seconds=1)
    session.flush()
    second_claim = service.claim(job_id=job.id)
    assert second_claim is not None
    assert second_claim.run_token is not None
    assert second_claim.run_token != first_token

    stale_document = DiscoveredDocument(
        external_file_id="stale-worker-document",
        name="Stale.pdf",
        mime_type="application/pdf",
        source_url="https://drive.example.test/stale",
        text="A stale worker must not change the snapshot.",
    )
    assert service.apply_reconciliation(job_id=job.id, run_token=first_token, documents=[stale_document]) is None
    assert service.fail(job_id=job.id, error_code="stale_worker", expected_run_token=first_token) is None
    assert service.release_for_retry(job_id=job.id, expected_run_token=first_token) is None

    fresh_document = DiscoveredDocument(
        external_file_id="fresh-worker-document",
        name="Fresh.pdf",
        mime_type="application/pdf",
        source_url="https://drive.example.test/fresh",
        text="Only the current worker may apply this snapshot.",
    )
    completed = service.apply_reconciliation(
        job_id=job.id,
        run_token=second_claim.run_token,
        documents=[fresh_document],
    )

    assert completed is not None
    assert completed.status is ProcessingJobStatus.READY
    assert folder.status == ProcessingJobStatus.READY.value
    assert {document.external_file_id for document in session.scalars(select(Document))} == {"fresh-worker-document"}


def test_failures_are_visible_to_admin_only_and_are_tenant_scoped(session: Session) -> None:
    organization, admin, folder = create_workspace(session)
    member = User(email="member@example.test")
    session.add(member)
    session.flush()
    session.add(
        Membership(
            organization_id=organization.id,
            user_id=member.id,
            role=MembershipRole.MEMBER,
            is_active=True,
        )
    )
    session.add_all(
        [
            Document(
                organization_id=organization.id,
                workspace_folder_id=folder.id,
                external_file_id="failed",
                name="Failed.pdf",
                mime_type="application/pdf",
                source_url="https://drive.example.test/failed",
                content_hash="",
                index_status="failed",
                error_code="text_extraction_failed",
            ),
            Document(
                organization_id=organization.id,
                workspace_folder_id=folder.id,
                external_file_id="ignored",
                name="Ignored.pptx",
                mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                source_url="https://drive.example.test/ignored",
                content_hash="",
                index_status="ignored",
                error_code="unsupported_file_type",
            ),
        ]
    )
    session.commit()

    visible = document_failures(
        workspace_folder_id=folder.id,
        organization_id=organization.id,
        user=admin,
        session=session,
    )

    assert {(row["name"], row["status"], row["error_code"]) for row in visible} == {
        ("Failed.pdf", "failed", "text_extraction_failed"),
        ("Ignored.pptx", "ignored", "unsupported_file_type"),
    }
    with pytest.raises(HTTPException) as member_error:
        document_failures(
            workspace_folder_id=folder.id,
            organization_id=organization.id,
            user=member,
            session=session,
        )
    assert member_error.value.status_code == 403

    other_organization, outsider, _ = create_workspace(session)
    with pytest.raises(HTTPException) as tenant_error:
        document_failures(
            workspace_folder_id=folder.id,
            organization_id=other_organization.id,
            user=outsider,
            session=session,
        )
    assert tenant_error.value.status_code == 403


def test_member_can_list_only_indexed_documents_in_their_own_folder(session: Session) -> None:
    organization, member, folder = create_workspace(session, role=MembershipRole.MEMBER)
    session.add_all(
        [
            Document(
                organization_id=organization.id,
                workspace_folder_id=folder.id,
                external_file_id="indexed-file",
                name="Indexed.pdf",
                mime_type="application/pdf",
                source_url="https://drive.example.test/indexed-file",
                content_hash="a" * 64,
                index_status="indexed",
            ),
            Document(
                organization_id=organization.id,
                workspace_folder_id=folder.id,
                external_file_id="failed-file",
                name="Failed.pdf",
                mime_type="application/pdf",
                source_url="https://drive.example.test/failed-file",
                content_hash="b" * 64,
                index_status="failed",
            ),
        ]
    )
    session.commit()

    result = documents(
        workspace_folder_id=folder.id,
        organization_id=organization.id,
        user=member,
        session=session,
    )

    assert result == [
        {
            "id": str(next(row.id for row in session.query(Document) if row.external_file_id == "indexed-file")),
            "name": "Indexed.pdf",
            "source_url": "https://drive.example.test/indexed-file",
            "modified_at": None,
        }
    ]


def test_document_listing_rejects_cross_organization_scope(session: Session) -> None:
    organization, member, folder = create_workspace(session, role=MembershipRole.MEMBER)
    other_organization, outsider, _ = create_workspace(session, role=MembershipRole.MEMBER)

    with pytest.raises(HTTPException) as error:
        documents(
            workspace_folder_id=folder.id,
            organization_id=other_organization.id,
            user=outsider,
            session=session,
        )

    assert error.value.status_code == 403
    assert member.id != outsider.id
    assert UUID(str(folder.organization_id)) == organization.id


def test_admin_removes_only_the_local_document_index_and_audits_it(session: Session) -> None:
    organization, admin, folder = create_workspace(session)
    service = IngestionService(session)
    job = service.enqueue(scope=OrganizationScope(organization.id), user_id=admin.id, workspace_folder_id=folder.id)
    service.reconcile(
        job_id=job.id,
        documents=[
            DiscoveredDocument(
                external_file_id="drive-file-1",
                name="Drive original remains.pdf",
                mime_type="application/pdf",
                source_url="https://drive.example.test/drive-file-1",
                text="This local index is removable.",
            )
        ],
    )
    document = session.scalar(select(Document).where(Document.external_file_id == "drive-file-1"))
    assert document is not None

    removed = service.remove_indexed_document(
        scope=OrganizationScope(organization.id),
        user_id=admin.id,
        workspace_folder_id=folder.id,
        document_id=document.id,
    )

    assert removed.id == document.id
    assert session.get(Document, document.id) is None
    assert session.scalar(select(DocumentChunk.id).where(DocumentChunk.document_id == document.id)) is None
    audit = session.scalar(select(AuditLog).where(AuditLog.target_id == document.id))
    assert audit is not None
    assert audit.action == "document_index.removed"


def test_reprocess_queues_a_regular_job_and_forces_only_selected_document_to_rebuild(session: Session) -> None:
    organization, admin, folder = create_workspace(session)
    service = IngestionService(session)
    first_job = service.enqueue(scope=OrganizationScope(organization.id), user_id=admin.id, workspace_folder_id=folder.id)
    initial = DiscoveredDocument(
        external_file_id="reprocess-me",
        name="Refresh.pdf",
        mime_type="application/pdf",
        source_url="https://drive.example.test/reprocess-me",
        text="Initial text.",
    )
    unchanged = DiscoveredDocument(
        external_file_id="leave-me",
        name="Stable.pdf",
        mime_type="application/pdf",
        source_url="https://drive.example.test/leave-me",
        text="Stable text.",
    )
    service.reconcile(job_id=first_job.id, documents=[initial, unchanged])
    selected = session.scalar(select(Document).where(Document.external_file_id == "reprocess-me"))
    stable = session.scalar(select(Document).where(Document.external_file_id == "leave-me"))
    assert selected is not None and stable is not None
    stable_chunk_id = session.scalar(select(DocumentChunk.id).where(DocumentChunk.document_id == stable.id))

    job = service.request_document_reprocess(
        scope=OrganizationScope(organization.id),
        user_id=admin.id,
        workspace_folder_id=folder.id,
        document_id=selected.id,
    )

    assert job.status is ProcessingJobStatus.QUEUED
    assert selected.content_hash == ""
    assert session.scalar(select(AuditLog.action).where(AuditLog.target_id == selected.id)) == "document_index.reprocess_requested"
    with pytest.raises(SyncAlreadyActive):
        service.remove_indexed_document(
            scope=OrganizationScope(organization.id), user_id=admin.id, workspace_folder_id=folder.id, document_id=selected.id
        )

    service.reconcile(job_id=job.id, documents=[initial, unchanged])

    assert session.scalar(select(DocumentChunk.text).where(DocumentChunk.document_id == selected.id)) == "Initial text."
    assert session.scalar(select(DocumentChunk.id).where(DocumentChunk.document_id == stable.id)) == stable_chunk_id


def test_member_and_foreign_scope_cannot_manage_an_indexed_document(session: Session) -> None:
    organization, _admin, folder = create_workspace(session)
    member = User(email="member-manage@example.test")
    session.add(member)
    session.flush()
    session.add(Membership(organization_id=organization.id, user_id=member.id, role=MembershipRole.MEMBER, is_active=True))
    document = Document(
        organization_id=organization.id,
        workspace_folder_id=folder.id,
        external_file_id="protected",
        name="Protected.pdf",
        mime_type="application/pdf",
        source_url="https://drive.example.test/protected",
        content_hash="hash",
        processing_version="v1",
        index_status="indexed",
    )
    session.add(document)
    session.flush()
    other_organization, outsider, _ = create_workspace(session)
    service = IngestionService(session)

    with pytest.raises(SyncAccessDenied):
        service.remove_indexed_document(
            scope=OrganizationScope(organization.id), user_id=member.id, workspace_folder_id=folder.id, document_id=document.id
        )
    with pytest.raises(SyncAccessDenied):
        service.request_document_reprocess(
            scope=OrganizationScope(other_organization.id), user_id=outsider.id, workspace_folder_id=folder.id, document_id=document.id
        )
    assert session.get(Document, document.id) is not None


def test_admin_removes_a_whole_local_workspace_without_touching_the_source(session: Session) -> None:
    organization, admin, folder = create_workspace(session)
    source_id = folder.source_id
    document = Document(
        organization_id=organization.id,
        workspace_folder_id=folder.id,
        external_file_id="local-file",
        name="Local.pdf",
        mime_type="application/pdf",
        source_url="https://drive.example.test/local-file",
        content_hash="a" * 64,
        processing_version="v1",
        index_status="indexed",
    )
    session.add(document)
    session.flush()
    chunk = DocumentChunk(
        organization_id=organization.id,
        workspace_folder_id=folder.id,
        document_id=document.id,
        position=0,
        text="Local indexed content.",
        search_text="Local indexed content.",
        embedding=[1.0, 0.0],
        embedding_model="test",
    )
    selection = WorkspaceFolderSelection(workspace_folder_id=folder.id, kind="folder", external_folder_id="folder-1")
    saved = SavedQuery(
        organization_id=organization.id,
        workspace_folder_id=folder.id,
        user_id=admin.id,
        name="Local query",
        query="What is local?",
        filters={},
    )
    terminal_job = ProcessingJob(
        organization_id=organization.id,
        workspace_folder_id=folder.id,
        idempotency_key="terminal-workspace-removal",
        status=ProcessingJobStatus.READY,
    )
    session.add_all([chunk, selection, saved, terminal_job])
    session.flush()

    removed = IngestionService(session).remove_workspace(
        scope=OrganizationScope(organization.id), user_id=admin.id, workspace_folder_id=folder.id
    )

    assert removed.id == folder.id
    assert removed.source_id == source_id
    assert removed.external_file_ids == ("local-file",)
    assert session.get(WorkspaceFolder, folder.id) is None
    assert session.get(Document, document.id) is None
    assert session.get(DocumentChunk, chunk.id) is None
    assert session.get(SavedQuery, saved.id) is None
    assert session.get(WorkspaceFolderSelection, selection.id) is None
    assert session.get(ProcessingJob, terminal_job.id) is None
    assert session.get(DataSource, source_id) is not None
    assert session.scalar(select(AuditLog.action).where(AuditLog.target_id == folder.id)) == "workspace_index.removed"


def test_workspace_removal_is_blocked_while_a_sync_is_active(session: Session) -> None:
    organization, admin, folder = create_workspace(session)
    document = Document(
        organization_id=organization.id,
        workspace_folder_id=folder.id,
        external_file_id="protected-workspace-file",
        name="Protected.pdf",
        mime_type="application/pdf",
        source_url="https://drive.example.test/protected-workspace-file",
        content_hash="a" * 64,
        processing_version="v1",
        index_status="indexed",
    )
    session.add(document)
    session.flush()
    IngestionService(session).enqueue(
        scope=OrganizationScope(organization.id), user_id=admin.id, workspace_folder_id=folder.id
    )

    with pytest.raises(SyncAlreadyActive):
        IngestionService(session).remove_workspace(
            scope=OrganizationScope(organization.id), user_id=admin.id, workspace_folder_id=folder.id
        )

    assert session.get(WorkspaceFolder, folder.id) is not None
    assert session.get(Document, document.id) is not None


def test_member_and_foreign_organization_cannot_remove_a_workspace(session: Session) -> None:
    organization, _admin, folder = create_workspace(session)
    member = User(email="workspace-member@example.test")
    session.add(member)
    session.flush()
    session.add(Membership(organization_id=organization.id, user_id=member.id, role=MembershipRole.MEMBER, is_active=True))
    other_organization, outsider, _ = create_workspace(session)
    service = IngestionService(session)

    with pytest.raises(SyncAccessDenied):
        service.remove_workspace(
            scope=OrganizationScope(organization.id), user_id=member.id, workspace_folder_id=folder.id
        )
    with pytest.raises(SyncAccessDenied):
        service.remove_workspace(
            scope=OrganizationScope(other_organization.id), user_id=outsider.id, workspace_folder_id=folder.id
        )

    assert session.get(WorkspaceFolder, folder.id) is not None
