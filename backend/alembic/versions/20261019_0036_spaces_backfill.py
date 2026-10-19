"""ADR-0021 Spaces: idempotent "Geral" backfill (everyone, every folder) and shadow mode."""

import sqlalchemy as sa

from alembic import op
from app.spaces.backfill import backfill_default_spaces

revision = "20261019_0036"
down_revision = "20261019_0035"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_context().as_sql:  # offline --sql has no connection to read organizations from
        return
    backfill_default_spaces(op.get_bind())


def downgrade():
    # Best effort: remove only what the migration created. The safe rollback is `rollout shadow`/`off` (plan §11);
    # the 0035 downgrade drops the tables anyway.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("DELETE FROM space_folder_grants WHERE disclosure->>'origin' = 'migration'"))
