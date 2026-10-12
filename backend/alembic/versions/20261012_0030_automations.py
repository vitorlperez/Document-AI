"""Automations (scheduled / folder-change reports) and their runs."""
import sqlalchemy as sa

from alembic import op

revision = "20261012_0030"
down_revision = "20261011_0029"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "automations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("trigger_kind", sa.String(20), nullable=False),
        sa.Column("trigger_config", sa.JSON(), nullable=False),
        sa.Column("scope", sa.JSON(), nullable=False),
        sa.Column("prompt", sa.String(1000), nullable=False),
        sa.Column("template", sa.String(20), nullable=False, server_default="summary"),
        sa.Column("output_formats", sa.JSON(), nullable=False),
        sa.Column("recipients", sa.JSON(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("trigger_kind IN ('schedule', 'folder_changed')", name="ck_automations_trigger_kind"),
        sa.CheckConstraint("template IN ('summary', 'table', 'alert')", name="ck_automations_template"),
    )
    op.create_index("ix_automations_org_created", "automations", ["organization_id", "created_at"])
    op.create_index("ix_automations_due", "automations", ["enabled", "trigger_kind", "next_run_at"])
    op.create_table(
        "automation_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("automation_id", sa.Uuid(), sa.ForeignKey("automations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="queued"),
        sa.Column("trigger_ref", sa.String(160), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("documents_considered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("questions_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result", sa.JSON()),
        sa.Column("error_code", sa.String(40)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("automation_id", "trigger_ref", name="uq_automation_runs_trigger_ref"),
        sa.CheckConstraint("status IN ('queued', 'running', 'ok', 'empty', 'quota', 'error')", name="ck_automation_runs_status"),
    )
    op.create_index("ix_automation_runs_automation_created", "automation_runs", ["automation_id", "created_at"])


def downgrade():
    op.drop_index("ix_automation_runs_automation_created", table_name="automation_runs")
    op.drop_table("automation_runs")
    op.drop_index("ix_automations_due", table_name="automations")
    op.drop_index("ix_automations_org_created", table_name="automations")
    op.drop_table("automations")
