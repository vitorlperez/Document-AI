"""One SharePoint data source per organization and Microsoft tenant.

Revision ID: 20260930_0020
Revises: 20260930_0019
"""

import sqlalchemy as sa

from alembic import op

revision = "20260930_0020"
down_revision = "20260930_0019"
branch_labels = None
depends_on = None

PREDICATE = "provider = 'sharepoint' AND provider_account_id IS NOT NULL"


def upgrade() -> None:
    # Partial index: existing Google/OneDrive/Notion rows are untouched.
    op.create_index(
        "uq_data_sources_sharepoint_tenant",
        "data_sources",
        ["organization_id", "provider_account_id"],
        unique=True,
        postgresql_where=sa.text(PREDICATE),
        sqlite_where=sa.text(PREDICATE),
    )


def downgrade() -> None:
    op.drop_index("uq_data_sources_sharepoint_tenant", table_name="data_sources")
