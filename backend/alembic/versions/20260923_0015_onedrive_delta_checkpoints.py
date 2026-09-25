"""Persist encrypted Microsoft Graph delta cursors per workspace selection."""

import sqlalchemy as sa

from alembic import op


revision = "20260923_0015"
down_revision = "20260915_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspace_folder_selections",
        sa.Column("encrypted_delta_link", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workspace_folder_selections", "encrypted_delta_link")
