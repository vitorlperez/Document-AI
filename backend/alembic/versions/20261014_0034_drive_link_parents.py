"""M58 multi-folder: Drive parents of each linked root (hierarchy for the scope catalog)."""

import sqlalchemy as sa

from alembic import op

revision = "20261014_0034"
down_revision = "20261014_0033"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("drive_folder_links", sa.Column("parent_external_ids", sa.JSON()))


def downgrade():
    op.drop_column("drive_folder_links", "parent_external_ids")
