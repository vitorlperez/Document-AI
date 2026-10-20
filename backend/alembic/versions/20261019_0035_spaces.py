"""ADR-0021 Spaces: spaces, members and folder grants (additive; behaviour unchanged until rollout)."""

import sqlalchemy as sa

from alembic import op

revision = "20261019_0035"
down_revision = "20261014_0034"
branch_labels = None
depends_on = None


def _org_fk():
    return sa.Column(
        "organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )


def _created_at():
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade():
    op.create_table(
        "spaces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _org_fk(),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("name_key", sa.String(120), nullable=False),
        sa.Column("description", sa.String(500)),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        _created_at(),
    )
    op.create_index("ix_spaces_organization_id", "spaces", ["organization_id"])
    op.create_index(
        "uq_spaces_org_name_active", "spaces", ["organization_id", "name_key"], unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.create_index(
        "uq_spaces_org_default", "spaces", ["organization_id"], unique=True,
        postgresql_where=sa.text("is_default AND archived_at IS NULL"),
    )

    op.create_table(
        "space_members",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _org_fk(),
        sa.Column("space_id", sa.Uuid(), sa.ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("added_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("removed_at", sa.DateTime(timezone=True)),
        sa.Column("removed_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        _created_at(),
        sa.CheckConstraint("role IN ('member','manager')", name="ck_space_member_role"),
    )
    op.create_index("ix_space_members_organization_id", "space_members", ["organization_id"])
    op.create_index("ix_space_members_space_id", "space_members", ["space_id"])
    op.create_index(
        "uq_space_members_active", "space_members", ["space_id", "user_id"], unique=True,
        postgresql_where=sa.text("removed_at IS NULL"),
    )
    op.create_index(
        "ix_space_members_user_active", "space_members", ["organization_id", "user_id"],
        postgresql_where=sa.text("removed_at IS NULL"),
    )

    op.create_table(
        "space_folder_grants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _org_fk(),
        sa.Column("space_id", sa.Uuid(), sa.ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "workspace_folder_id", sa.Uuid(), sa.ForeignKey("workspace_folders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("granted_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("disclosure", sa.JSON(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        _created_at(),
    )
    op.create_index("ix_space_folder_grants_organization_id", "space_folder_grants", ["organization_id"])
    op.create_index("ix_space_folder_grants_space_id", "space_folder_grants", ["space_id"])
    op.create_index(
        "uq_space_grants_active", "space_folder_grants", ["space_id", "workspace_folder_id"], unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "ix_space_grants_folder_active", "space_folder_grants", ["workspace_folder_id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.add_column(
        "organizations",
        sa.Column("spaces_resolver_mode", sa.String(8), nullable=False, server_default="off"),
    )
    op.add_column("membership_invitations", sa.Column("space_ids", sa.JSON()))


def downgrade():
    op.drop_column("membership_invitations", "space_ids")
    op.drop_column("organizations", "spaces_resolver_mode")
    op.drop_table("space_folder_grants")
    op.drop_table("space_members")
    op.drop_table("spaces")
