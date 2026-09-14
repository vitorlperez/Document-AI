"""Retain safe Google account metadata for the integration management UI."""

import sqlalchemy as sa

from alembic import op

revision = "20260914_0013"
down_revision = "20260913_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("data_sources", sa.Column("account_email", sa.String(length=320), nullable=True))
    op.alter_column("data_sources", "encrypted_credentials", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE data_sources SET encrypted_credentials = '' WHERE encrypted_credentials IS NULL")
    op.alter_column("data_sources", "encrypted_credentials", existing_type=sa.Text(), nullable=False)
    op.drop_column("data_sources", "account_email")
