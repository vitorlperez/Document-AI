"""Make provider subject, not e-mail, the identity-linking key."""

from alembic import op

revision = "20260910_0003"
down_revision = "20260910_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("users_email_key", "users", type_="unique")
    op.create_index("ix_users_email", "users", ["email"])


def downgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.create_unique_constraint("users_email_key", "users", ["email"])
