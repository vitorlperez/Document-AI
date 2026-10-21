"""Spaces always enforce (decision 2026-10-20): cover everyone/everything in the default Space, drop the rollout mode.

The resolver no longer has ``off``/``shadow``. Before the column goes away every organization gets its default
Space ("Geral") with every active person and every folder that no Space grants, so enforcing hides nothing
from anyone who could read it yesterday. Idempotent; the data insert is skipped in offline ``--sql`` mode.
"""

import sqlalchemy as sa

from alembic import op
from app.spaces.backfill import ensure_default_space_coverage

revision = "20261020_0038"
down_revision = "20261020_0037"
branch_labels = None
depends_on = None


def upgrade():
    if not op.get_context().as_sql:
        ensure_default_space_coverage(op.get_bind())
    op.drop_column("organizations", "spaces_resolver_mode")


def downgrade():
    # Recreated as `enforce` (the only mode that existed at this revision); the 0035 downgrade drops it again.
    op.add_column(
        "organizations",
        sa.Column("spaces_resolver_mode", sa.String(8), nullable=False, server_default="enforce"),
    )
