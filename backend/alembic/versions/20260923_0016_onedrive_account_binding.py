"""Bind OneDrive data sources to their Microsoft drive identity."""

import sqlalchemy as sa

from alembic import op


revision = "20260923_0016"
down_revision = "20260923_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "data_sources",
        sa.Column("provider_account_id", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("data_sources", "provider_account_id")
