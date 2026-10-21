"""Spaces at folder level: a Space can be granted a library folder (any depth) with everything below it.

``space_node_grants`` complements ``space_folder_grants`` (whole admitted scope): the existing grants are untouched
and keep their meaning. The grant names the folder by its provider id (source + external id), so catalog pruning
does not drop it and a folder missing from the catalog grants nothing.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261021_0040"
down_revision = "20261020_0039"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "space_node_grants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("space_id", sa.Uuid(), sa.ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.Uuid(), sa.ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("granted_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("disclosure", sa.JSON(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_space_node_grants_organization_id", "space_node_grants", ["organization_id"])
    op.create_index("ix_space_node_grants_space_id", "space_node_grants", ["space_id"])
    op.create_index(
        "uq_space_node_grants_active", "space_node_grants", ["space_id", "source_id", "external_id"], unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"), sqlite_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_space_node_grants_source_active", "space_node_grants", ["source_id", "external_id"],
        postgresql_where=sa.text("revoked_at IS NULL"), sqlite_where=sa.text("revoked_at IS NULL"),
    )


def downgrade():
    op.drop_table("space_node_grants")
