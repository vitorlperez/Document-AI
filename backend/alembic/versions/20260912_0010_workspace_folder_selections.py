"""Add multi-root Google Drive workspace scopes without removing legacy data."""

from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import context, op

revision = "20260912_0010"
down_revision = "20260911_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_folder_selections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_folder_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("external_folder_id", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "(kind = 'folder' AND external_folder_id <> '') "
            "OR (kind IN ('root_files', 'all_accessible') AND external_folder_id = '')",
            name="ck_workspace_folder_selection_kind",
        ),
        sa.ForeignKeyConstraint(["workspace_folder_id"], ["workspace_folders.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_workspace_folder_selections_workspace_folder_id", "workspace_folder_selections", ["workspace_folder_id"])
    op.create_index(
        "uq_workspace_folder_selection_kind_external",
        "workspace_folder_selections",
        ["workspace_folder_id", "kind", "external_folder_id"],
        unique=True,
    )
    if context.is_offline_mode():
        # Offline SQL is a deployment-plan artifact, so it cannot fetch legacy
        # UUIDs into Python. PostgreSQL evaluates this only when the plan is
        # executed; the live migration below deliberately avoids requiring an
        # extension such as pgcrypto.
        op.execute(
            "INSERT INTO workspace_folder_selections "
            "(id, workspace_folder_id, kind, external_folder_id, created_at) "
            "SELECT gen_random_uuid(), id, 'folder', external_folder_id, created_at "
            "FROM workspace_folders"
        )
        return

    bind = op.get_bind()
    legacy_rows = bind.execute(sa.text("SELECT id, external_folder_id, created_at FROM workspace_folders"))
    for row in legacy_rows.mappings():
        bind.execute(
            sa.text(
                "INSERT INTO workspace_folder_selections "
                "(id, workspace_folder_id, kind, external_folder_id, created_at) "
                "VALUES (:id, :workspace_folder_id, 'folder', :external_folder_id, :created_at)"
            ),
            {
                "id": uuid4(),
                "workspace_folder_id": row["id"],
                "external_folder_id": row["external_folder_id"],
                "created_at": row["created_at"],
            },
        )


def downgrade() -> None:
    op.drop_table("workspace_folder_selections")
