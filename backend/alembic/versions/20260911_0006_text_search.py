"""Add indexed PostgreSQL full-text retrieval for scoped document chunks."""

import sqlalchemy as sa

from alembic import op

revision = "20260911_0006"
down_revision = "20260911_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column("search_text", sa.Text(), nullable=False, server_default=""),
    )
    op.execute(
        "UPDATE document_chunks AS chunks SET search_text = documents.name || E'\\n' || chunks.text "
        "FROM documents WHERE documents.id = chunks.document_id"
    )
    op.execute(
        "ALTER TABLE document_chunks ADD COLUMN search_vector tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple', search_text)) STORED"
    )
    op.create_index(
        "ix_document_chunks_search_vector",
        "document_chunks",
        ["search_vector"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_document_chunks_organization_folder",
        "document_chunks",
        ["organization_id", "workspace_folder_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_organization_folder", table_name="document_chunks")
    op.drop_index("ix_document_chunks_search_vector", table_name="document_chunks")
    op.drop_column("document_chunks", "search_vector")
    op.drop_column("document_chunks", "search_text")
