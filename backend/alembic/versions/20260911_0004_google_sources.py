"""Add Google sources, OAuth state and workspace folders."""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260911_0004"
down_revision = "20260910_0003"
branch_labels = None
depends_on = None
def upgrade() -> None:
    op.create_table("data_sources", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("provider", sa.String(40), nullable=False), sa.Column("encrypted_credentials", sa.Text(), nullable=False), sa.Column("status", sa.String(40), nullable=False), sa.Column("connected_by_user_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("last_synced_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")), sa.ForeignKeyConstraint(["organization_id"],["organizations.id"],ondelete="CASCADE"),sa.ForeignKeyConstraint(["connected_by_user_id"],["users.id"],ondelete="RESTRICT"))
    op.create_index("ix_data_sources_organization_id", "data_sources", ["organization_id"])
    op.create_table("oauth_connection_states", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("session_hash",sa.String(64),nullable=False),sa.Column("state_hash",sa.String(64),nullable=False,unique=True),sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False),sa.Column("consumed_at",sa.DateTime(timezone=True)),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("now()")),sa.ForeignKeyConstraint(["organization_id"],["organizations.id"],ondelete="CASCADE"),sa.ForeignKeyConstraint(["user_id"],["users.id"],ondelete="CASCADE"))
    op.create_index("ix_oauth_connection_states_organization_id", "oauth_connection_states", ["organization_id"])
    op.create_table("workspace_folders",sa.Column("id",postgresql.UUID(as_uuid=True),primary_key=True),sa.Column("organization_id",postgresql.UUID(as_uuid=True),nullable=False),sa.Column("source_id",postgresql.UUID(as_uuid=True),nullable=False),sa.Column("external_folder_id",sa.String(255),nullable=False),sa.Column("name",sa.String(512),nullable=False),sa.Column("uniform_access_confirmed",sa.Boolean(),nullable=False),sa.Column("status",sa.String(40),nullable=False),sa.Column("last_synced_at",sa.DateTime(timezone=True)),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False,server_default=sa.text("now()")),sa.ForeignKeyConstraint(["organization_id"],["organizations.id"],ondelete="CASCADE"),sa.ForeignKeyConstraint(["source_id"],["data_sources.id"],ondelete="CASCADE"))
    op.create_index("ix_workspace_folders_organization_id","workspace_folders",["organization_id"]); op.create_index("ix_workspace_folders_source_id","workspace_folders",["source_id"]); op.create_index("uq_workspace_folders_source_external","workspace_folders",["source_id","external_folder_id"],unique=True)
def downgrade() -> None:
    op.drop_table("workspace_folders"); op.drop_table("oauth_connection_states"); op.drop_table("data_sources")
