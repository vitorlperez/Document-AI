"""Add explicit expiring platform-staff Company grants."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260911_0009"
down_revision = "20260911_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_staff",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_platform_staff_user_id", "platform_staff", ["user_id"])
    op.create_table(
        "staff_access_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("platform_staff_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.String(240), nullable=False),
        sa.Column("granted_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["platform_staff_id"], ["platform_staff.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_staff_access_grants_platform_staff_id", "staff_access_grants", ["platform_staff_id"])
    op.create_index("ix_staff_access_grants_organization_id", "staff_access_grants", ["organization_id"])
    op.create_index("ix_staff_access_grants_expires_at", "staff_access_grants", ["expires_at"])
    op.create_index("ix_staff_access_grants_revoked_at", "staff_access_grants", ["revoked_at"])
    op.create_index(
        "ix_staff_access_grants_staff_org_active",
        "staff_access_grants",
        ["platform_staff_id", "organization_id", "expires_at", "revoked_at"],
    )


def downgrade() -> None:
    op.drop_table("staff_access_grants")
    op.drop_table("platform_staff")
