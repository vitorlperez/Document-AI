"""Add asynchronous ingestion jobs and tenant-scoped extracted documents."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260911_0005"
down_revision = "20260911_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    processing_job_status = postgresql.ENUM(
        "queued", "syncing", "ready", "partial_failure", "failed", name="processing_job_status", create_type=False
    )
    processing_job_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "processing_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_folder_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", processing_job_status, nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("run_token", sa.String(64)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_folder_id"], ["workspace_folders.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_processing_jobs_organization_id", "processing_jobs", ["organization_id"])
    op.create_index("ix_processing_jobs_workspace_folder_id", "processing_jobs", ["workspace_folder_id"])
    op.create_index(
        "uq_active_processing_jobs_folder",
        "processing_jobs",
        ["organization_id", "workspace_folder_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'syncing')"),
    )
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_folder_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_file_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("source_url", sa.String(2048), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("modified_at", sa.DateTime(timezone=True)),
        sa.Column("indexed_at", sa.DateTime(timezone=True)),
        sa.Column("processing_version", sa.String(40), nullable=False, server_default="v1"),
        sa.Column("index_status", sa.String(40), nullable=False),
        sa.Column("error_code", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_folder_id"], ["workspace_folders.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_folder_id", "external_file_id", name="uq_documents_folder_external"),
    )
    op.create_index(
        "ix_documents_organization_folder_status",
        "documents",
        ["organization_id", "workspace_folder_id", "index_status"],
    )
    op.create_table(
        "document_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_folder_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_folder_id"], ["workspace_folders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id", "position", name="uq_document_chunks_document_position"),
    )


def downgrade() -> None:
    op.drop_table("document_chunks")
    op.drop_index("ix_documents_organization_folder_status", table_name="documents")
    op.drop_table("documents")
    op.drop_index("uq_active_processing_jobs_folder", table_name="processing_jobs")
    op.drop_table("processing_jobs")
    postgresql.ENUM(name="processing_job_status").drop(op.get_bind(), checkfirst=True)
