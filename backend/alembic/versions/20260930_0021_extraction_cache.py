"""OCR extraction cache per organization.

Revision ID: 20260930_0021
Revises: 20260930_0020
"""

import sqlalchemy as sa

from alembic import op

revision = "20260930_0021"
down_revision = "20260930_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "extraction_cache",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("engine", sa.String(40), nullable=False),
        sa.Column("engine_version", sa.String(40), nullable=False),
        sa.Column("cache_key", sa.String(160), nullable=False),
        sa.Column("page_texts", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "organization_id", "engine", "engine_version", "cache_key", name="uq_extraction_cache_key"
        ),
    )
    op.create_index("ix_extraction_cache_organization_id", "extraction_cache", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_extraction_cache_organization_id", table_name="extraction_cache")
    op.drop_table("extraction_cache")
