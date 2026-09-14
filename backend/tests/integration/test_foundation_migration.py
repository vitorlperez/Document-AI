import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.core.scoping import OrganizationScope
from app.identity.models import User
from app.ingestion.models import ProcessingJob, ProcessingJobStatus
from app.integrations.models import DataSource
from app.knowledge.models import Document, DocumentChunk
from app.knowledge.search import TextSearchService
from app.organizations.models import Membership, MembershipRole, Organization
from app.workspaces.models import WorkspaceFolder

pytestmark = pytest.mark.postgres

BACKEND_DIR = Path(__file__).resolve().parents[2]


def run_alembic(*arguments: str, database_url: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_DIR,
        env=os.environ | {"DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_foundation_migration_applies_and_reverts_on_disposable_postgres(test_database_url: str) -> None:
    """Requires TEST_DATABASE_URL to be a dedicated disposable PostgreSQL database."""
    run_alembic("downgrade", "base", database_url=test_database_url)
    try:
        run_alembic("upgrade", "head", database_url=test_database_url)
        engine = create_engine(test_database_url)
        inspector = inspect(engine)
        assert {
            "organizations",
            "users",
            "memberships",
            "audit_logs",
            "auth_identities",
            "user_sessions",
            "membership_invitations",
            "data_sources",
            "oauth_connection_states",
            "workspace_folders",
            "workspace_folder_selections",
            "processing_jobs",
            "documents",
            "document_chunks",
            "saved_queries",
            "usage_records",
            "platform_staff",
            "staff_access_grants",
        } <= set(inspector.get_table_names())
        membership_indexes = {index["name"] for index in inspector.get_indexes("memberships")}
        assert "uq_memberships_active_org_user" in membership_indexes
        invitation_indexes = {index["name"] for index in inspector.get_indexes("membership_invitations")}
        assert "uq_membership_invitations_pending_org_email" in invitation_indexes
        user_indexes = {index["name"] for index in inspector.get_indexes("users")}
        assert "ix_users_email" in user_indexes
        user_unique_constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("users")}
        assert "users_email_key" not in user_unique_constraints
        workspace_indexes = {index["name"] for index in inspector.get_indexes("workspace_folders")}
        assert "uq_workspace_folders_source_external" in workspace_indexes
        selection_indexes = {index["name"]: index for index in inspector.get_indexes("workspace_folder_selections")}
        assert selection_indexes["uq_workspace_folder_selection_kind_external"]["unique"] is True
        assert "ix_workspace_folder_selections_workspace_folder_id" in selection_indexes
        processing_job_indexes = {index["name"]: index for index in inspector.get_indexes("processing_jobs")}
        assert processing_job_indexes["uq_active_processing_jobs_folder"]["unique"] is True
        assert {"ix_processing_jobs_organization_id", "ix_processing_jobs_workspace_folder_id"} <= set(
            processing_job_indexes
        )
        documents_indexes = {index["name"] for index in inspector.get_indexes("documents")}
        assert "ix_documents_organization_folder_status" in documents_indexes
        document_unique_constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("documents")}
        assert "uq_documents_folder_external" in document_unique_constraints
        chunk_unique_constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("document_chunks")}
        assert "uq_document_chunks_document_position" in chunk_unique_constraints
        chunk_indexes = {index["name"] for index in inspector.get_indexes("document_chunks")}
        assert {"ix_document_chunks_organization_folder", "ix_document_chunks_search_vector"} <= chunk_indexes
        assert {"search_text", "search_vector", "embedding", "embedding_model"} <= {
            column["name"] for column in inspector.get_columns("document_chunks")
        }
        saved_query_columns = {column["name"] for column in inspector.get_columns("saved_queries")}
        assert {"organization_id", "workspace_folder_id", "user_id", "name", "query", "filters"} <= saved_query_columns
        usage_constraints = {constraint["name"] for constraint in inspector.get_unique_constraints("usage_records")}
        assert "uq_usage_records_org_period_metric" in usage_constraints
        staff_columns = {column["name"] for column in inspector.get_columns("platform_staff")}
        assert {"id", "user_id", "is_active"} <= staff_columns
        grant_columns = {column["name"] for column in inspector.get_columns("staff_access_grants")}
        assert {"id", "platform_staff_id", "organization_id", "reason", "expires_at", "revoked_at"} <= grant_columns
        grant_indexes = {index["name"] for index in inspector.get_indexes("staff_access_grants")}
        assert "ix_staff_access_grants_staff_org_active" in grant_indexes
        assert {foreign_key["referred_table"] for foreign_key in inspector.get_foreign_keys("processing_jobs")} == {
            "organizations",
            "workspace_folders",
        }
        assert {foreign_key["referred_table"] for foreign_key in inspector.get_foreign_keys("documents")} == {
            "organizations",
            "workspace_folders",
        }
        assert {foreign_key["referred_table"] for foreign_key in inspector.get_foreign_keys("document_chunks")} == {
            "organizations",
            "workspace_folders",
            "documents",
        }
        with engine.connect() as connection:
            active_job_index = connection.scalar(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE schemaname = current_schema() "
                    "AND tablename = 'processing_jobs' "
                    "AND indexname = 'uq_active_processing_jobs_folder'"
                )
            )
        assert active_job_index is not None
        assert "WHERE (status = ANY (ARRAY['queued'::processing_job_status, 'syncing'::processing_job_status]))" in active_job_index
        with engine.connect() as connection:
            full_text_index = connection.scalar(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE schemaname = current_schema() "
                    "AND tablename = 'document_chunks' "
                    "AND indexname = 'ix_document_chunks_search_vector'"
                )
            )
        assert full_text_index is not None
        assert "USING gin (search_vector)" in full_text_index
        with Session(engine) as session:
            organization = Organization(name="FTS organization")
            member = User(email="fts-member@example.test")
            session.add_all([organization, member])
            session.flush()
            session.add(
                Membership(
                    organization_id=organization.id,
                    user_id=member.id,
                    role=MembershipRole.MEMBER,
                    is_active=True,
                )
            )
            source = DataSource(
                organization_id=organization.id,
                provider="google_drive",
                encrypted_credentials="ciphertext",
                status="connected",
                connected_by_user_id=member.id,
            )
            session.add(source)
            session.flush()
            folder = WorkspaceFolder(
                organization_id=organization.id,
                source_id=source.id,
                external_folder_id="fts-folder",
                name="FTS folder",
                uniform_access_confirmed=True,
                status="ready",
            )
            session.add(folder)
            session.flush()
            session.add(
                ProcessingJob(
                    organization_id=organization.id,
                    workspace_folder_id=folder.id,
                    status=ProcessingJobStatus.QUEUED,
                    idempotency_key="a" * 64,
                )
            )
            document = Document(
                organization_id=organization.id,
                workspace_folder_id=folder.id,
                external_file_id="fts-document",
                name="Campaign scope.pdf",
                mime_type="application/pdf",
                source_url="https://drive.example.test/fts-document",
                content_hash="b" * 64,
                processing_version="v1",
                index_status="indexed",
            )
            session.add(document)
            session.flush()
            session.add(
                DocumentChunk(
                    organization_id=organization.id,
                    workspace_folder_id=folder.id,
                    document_id=document.id,
                    position=0,
                    text="The campaign launches in September.",
                    search_text="Campaign scope.pdf\nThe campaign launches in September.",
                )
            )
            session.commit()

            assert session.scalar(text("SELECT role::text FROM memberships")) == "member"
            assert session.scalar(text("SELECT status::text FROM processing_jobs")) == "queued"
            hits = TextSearchService(session).search(
                scope=OrganizationScope(organization.id),
                user_id=member.id,
                workspace_folder_id=folder.id,
                query="September",
            )
            assert [hit.document_name for hit in hits.items] == ["Campaign scope.pdf"]
        engine.dispose()
    finally:
        run_alembic("downgrade", "base", database_url=test_database_url)
