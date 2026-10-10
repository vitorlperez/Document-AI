"""In-app notifications, notification preferences and followed ("living") saved queries."""
import sqlalchemy as sa

from alembic import op

revision = "20261010_0028"
down_revision = "20261001_0027"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_notifications_user_org_created", "notifications", ["user_id", "organization_id", "created_at"])
    op.create_table(
        "notification_preferences",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_notification_preferences_org_user"),
    )
    with op.batch_alter_table("saved_queries") as batch:
        batch.add_column(sa.Column("followed", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("last_answer", sa.JSON()))
        batch.add_column(sa.Column("last_checked_at", sa.DateTime(timezone=True)))


def downgrade():
    with op.batch_alter_table("saved_queries") as batch:
        batch.drop_column("last_checked_at")
        batch.drop_column("last_answer")
        batch.drop_column("followed")
    op.drop_table("notification_preferences")
    op.drop_index("ix_notifications_user_org_created", table_name="notifications")
    op.drop_table("notifications")
