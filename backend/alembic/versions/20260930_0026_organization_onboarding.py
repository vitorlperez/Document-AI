"""Persist first-organization setup and each member's conversation tour."""
import sqlalchemy as sa

from alembic import op

revision = "20260930_0026"
down_revision = "20260930_0025"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("organizations", sa.Column(
        "onboarding_step", sa.String(24), nullable=False, server_default="welcome",
    ))
    op.add_column("organizations", sa.Column(
        "onboarding_completed_at", sa.DateTime(timezone=True), nullable=True,
    ))
    op.add_column("memberships", sa.Column(
        "tour_completed_at", sa.DateTime(timezone=True), nullable=True,
    ))
    # Preserve the established experience for every existing tenant and member.
    # No timestamp default: organizations/members created after this stay pending.
    op.execute("UPDATE organizations SET onboarding_step = 'complete', onboarding_completed_at = CURRENT_TIMESTAMP")
    op.execute("UPDATE memberships SET tour_completed_at = CURRENT_TIMESTAMP")


def downgrade():
    op.drop_column("memberships", "tour_completed_at")
    op.drop_column("organizations", "onboarding_completed_at")
    op.drop_column("organizations", "onboarding_step")
