"""Per-user MCP organization binding."""
import sqlalchemy as sa

from alembic import op

revision = "20260930_0025"
down_revision = "20260930_0024"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mcp_connections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_ids", sa.JSON()),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_mcp_connections_organization_id", "mcp_connections", ["organization_id"])
    op.create_index(
        "uq_mcp_connections_active_user", "mcp_connections", ["user_id"], unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
        sqlite_where=sa.text("revoked_at IS NULL"),
    )


def downgrade():
    op.drop_index("uq_mcp_connections_active_user", table_name="mcp_connections")
    op.drop_index("ix_mcp_connections_organization_id", table_name="mcp_connections")
    op.drop_table("mcp_connections")
