"""Account types (personal/business), local trial, comps and a provider-agnostic subscription mirror.

Existing organizations stay exactly as they are: ``account_type='business'``, ``plan_key='legacy'``,
``entitlement_source='legacy'`` (the column defaults). There is no heuristic classification and no data UPDATE.
The server defaults are what makes old rows legacy; code that creates organizations always passes an explicit plan.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261022_0041"
down_revision = "20261021_0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("account_type", sa.String(16), nullable=False, server_default="business"))
    op.add_column("organizations", sa.Column("plan_key", sa.String(32), nullable=False, server_default="legacy"))
    op.add_column("organizations", sa.Column("entitlement_source", sa.String(16), nullable=False, server_default="legacy"))
    op.add_column("organizations", sa.Column("trial_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("organizations", sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("organizations", sa.Column("account_type_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("organizations", sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("organizations", sa.Column("billing_provider", sa.String(32), nullable=True))
    op.add_column("organizations", sa.Column("billing_customer_id", sa.String(128), nullable=True))
    op.create_foreign_key(
        "fk_organizations_created_by_user_id", "organizations", "users", ["created_by_user_id"], ["id"], ondelete="SET NULL"
    )
    op.create_check_constraint(
        "ck_organizations_account_type", "organizations", "account_type IN ('personal','business')"
    )
    op.create_index("ix_organizations_created_by_user_id", "organizations", ["created_by_user_id"])

    op.add_column("platform_staff", sa.Column("role", sa.String(16), nullable=False, server_default="support"))

    op.create_table(
        "organization_comps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_key", sa.String(32), nullable=False),
        sa.Column("limits_override", sa.JSON(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(240), nullable=False),
        sa.Column("granted_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["revoked_by_user_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_organization_comps_organization_id", "organization_comps", ["organization_id"])
    op.create_index(
        "uq_organization_comps_active_org", "organization_comps", ["organization_id"], unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("external_customer_id", sa.String(128), nullable=True),
        sa.Column("external_subscription_id", sa.String(128), nullable=False),
        sa.Column("plan_key", sa.String(32), nullable=False),
        sa.Column("interval", sa.String(8), nullable=False, server_default="month"),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("seats", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("past_due_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("coupon_code", sa.String(64), nullable=True),
        sa.Column("discount_summary", sa.JSON(), nullable=True),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_subscriptions_organization_id", "subscriptions", ["organization_id"])
    op.create_index(
        "uq_subscriptions_provider_external", "subscriptions", ["provider", "external_subscription_id"], unique=True
    )

    op.create_table(
        "billing_events",
        sa.Column("id", sa.String(190), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("type", sa.String(48), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(240), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("billing_events")
    op.drop_index("uq_subscriptions_provider_external", table_name="subscriptions")
    op.drop_index("ix_subscriptions_organization_id", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_index("uq_organization_comps_active_org", table_name="organization_comps")
    op.drop_index("ix_organization_comps_organization_id", table_name="organization_comps")
    op.drop_table("organization_comps")
    op.drop_column("platform_staff", "role")
    op.drop_index("ix_organizations_created_by_user_id", table_name="organizations")
    op.drop_constraint("ck_organizations_account_type", "organizations", type_="check")
    op.drop_constraint("fk_organizations_created_by_user_id", "organizations", type_="foreignkey")
    for column in (
        "billing_customer_id", "billing_provider", "created_by_user_id", "account_type_changed_at", "trial_ends_at",
        "trial_started_at", "entitlement_source", "plan_key", "account_type",
    ):
        op.drop_column("organizations", column)
