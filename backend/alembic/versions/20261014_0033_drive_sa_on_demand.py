"""M58 on-demand robots: per-project IAM creation throttle marker."""

import sqlalchemy as sa

from alembic import op

revision = "20261014_0033"
down_revision = "20261014_0032"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "google_sa_projects", sa.Column("last_iam_create_at", sa.DateTime(timezone=True))
    )


def downgrade():
    op.drop_column("google_sa_projects", "last_iam_create_at")
