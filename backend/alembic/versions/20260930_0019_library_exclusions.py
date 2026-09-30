"""Persist explicit Library removals independently of provider synchronization."""

import sqlalchemy as sa

from alembic import op

revision = "20260930_0019"
down_revision = "20260929_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "library_exclusions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_library_exclusions_organization_id", "library_exclusions", ["organization_id"])
    op.create_index("ix_library_exclusions_source_id", "library_exclusions", ["source_id"])
    op.create_index("uq_library_exclusions_source_external", "library_exclusions", ["source_id", "external_id"], unique=True)


def downgrade() -> None:
    op.drop_table("library_exclusions")
