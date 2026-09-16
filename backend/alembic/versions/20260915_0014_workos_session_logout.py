"""Store the remote AuthKit session identifier for global logout."""

import sqlalchemy as sa

from alembic import op


revision = "20260915_0014"
down_revision = "20260914_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user_sessions", sa.Column("provider_session_id", sa.String(length=255), nullable=True))
    op.create_index("ix_user_sessions_provider_session_id", "user_sessions", ["provider_session_id"])


def downgrade() -> None:
    op.drop_index("ix_user_sessions_provider_session_id", table_name="user_sessions")
    op.drop_column("user_sessions", "provider_session_id")
