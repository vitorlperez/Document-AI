"""Bind a Google OAuth reauthorization state to its existing source."""

import sqlalchemy as sa

from alembic import op


revision = "20260912_0011"
down_revision = "20260912_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("oauth_connection_states", sa.Column("source_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_oauth_connection_states_source_id",
        "oauth_connection_states",
        "data_sources",
        ["source_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_oauth_connection_states_source_id", "oauth_connection_states", type_="foreignkey")
    op.drop_column("oauth_connection_states", "source_id")
