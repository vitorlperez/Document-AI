"""Content-free audit events for programmatic access."""
import sqlalchemy as sa

from alembic import op

revision = "20260930_0023"
down_revision = "20260930_0022"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "api_audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("credential_id", sa.Uuid()),
        sa.Column("user_id", sa.Uuid()),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("http_status", sa.Integer()),
        sa.Column("request_id", sa.String(64)),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("result_count", sa.Integer()),
        sa.Column("query_sha256", sa.String(64)),
        sa.Column("query_length", sa.Integer()),
        sa.Column("document_id", sa.Uuid()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_api_audit_events_org_created", "api_audit_events", ["organization_id", "created_at"])
    op.create_index("ix_api_audit_events_credential", "api_audit_events", ["credential_id", "created_at"])


def downgrade():
    op.drop_index("ix_api_audit_events_credential", table_name="api_audit_events")
    op.drop_index("ix_api_audit_events_org_created", table_name="api_audit_events")
    op.drop_table("api_audit_events")
