"""Durable manual recursive synchronization history."""

import sqlalchemy as sa

from alembic import op

revision = "20260929_0018"
down_revision = "20260928_0017"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "manual_sync_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("scope_kind", sa.String(16), nullable=False),
        sa.Column("scope_external_id", sa.String(255)),
        sa.Column("scope_name", sa.String(512), nullable=False),
        sa.Column(
            "triggered_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("triggered_by", sa.String(320), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("progress", sa.JSON(), nullable=False),
    )
    op.create_index("ix_manual_sync_runs_organization_id", "manual_sync_runs", ["organization_id"])
    op.add_column("processing_jobs", sa.Column("manual_run_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_processing_jobs_manual_run",
        "processing_jobs",
        "manual_sync_runs",
        ["manual_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_processing_jobs_manual_run_id", "processing_jobs", ["manual_run_id"])


def downgrade():
    op.drop_index("ix_processing_jobs_manual_run_id", table_name="processing_jobs")
    op.drop_constraint("fk_processing_jobs_manual_run", "processing_jobs", type_="foreignkey")
    op.drop_column("processing_jobs", "manual_run_id")
    op.drop_table("manual_sync_runs")
