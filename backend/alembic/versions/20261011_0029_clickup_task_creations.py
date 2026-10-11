"""Ledger of ClickUp tasks created from an answer (idempotency, outcome and audit ids; ADR-0020)."""
import sqlalchemy as sa

from alembic import op

revision = "20261011_0029"
down_revision = "20261010_0028"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "clickup_task_creations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.Uuid(), sa.ForeignKey("conversation_messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("list_id", sa.String(64), nullable=False),
        sa.Column("task_id", sa.String(64)),
        sa.Column("task_url", sa.String(2048)),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("error_code", sa.String(40)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_clickup_task_creations_org_key"),
        sa.CheckConstraint("status IN ('pending', 'created', 'failed')", name="ck_clickup_task_creations_status"),
    )
    op.create_index("ix_clickup_task_creations_user_created", "clickup_task_creations", ["user_id", "created_at"])
    op.create_index("ix_clickup_task_creations_message", "clickup_task_creations", ["message_id"])


def downgrade():
    op.drop_index("ix_clickup_task_creations_message", table_name="clickup_task_creations")
    op.drop_index("ix_clickup_task_creations_user_created", table_name="clickup_task_creations")
    op.drop_table("clickup_task_creations")
