"""M58 dedicated Drive robots and explicit folder grants."""

import sqlalchemy as sa
from alembic import op

revision = "20261014_0032"
down_revision = "20261013_0031"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "google_sa_projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("gcp_project_id", sa.String(255), nullable=False, unique=True),
        sa.Column("sa_quota", sa.Integer(), nullable=False, server_default="100"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "google_sa_identities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("google_sa_projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("sa_email", sa.String(320), nullable=False, unique=True),
        sa.Column("encrypted_key", sa.Text()),
        sa.Column("key_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(16), nullable=False, server_default="free"),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            unique=True,
        ),
        sa.Column("group_email", sa.String(320)),
        *[
            sa.Column(name, sa.DateTime(timezone=True))
            for name in ("assigned_at", "rotated_at", "retired_at")
        ],
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('free','assigned','retired','compromised')",
            name="ck_google_sa_identity_status",
        ),
        sa.CheckConstraint(
            "(status = 'free' AND organization_id IS NULL AND assigned_at IS NULL) OR (status <> 'free' AND organization_id IS NOT NULL)",
            name="ck_google_sa_identity_assignment",
        ),
    )
    op.add_column(
        "data_sources",
        sa.Column(
            "sa_identity_id",
            sa.Uuid(),
            sa.ForeignKey("google_sa_identities.id", ondelete="RESTRICT"),
        ),
    )
    op.create_index(
        "uq_data_sources_google_sa_org",
        "data_sources",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("provider = 'google_drive_sa'"),
        sqlite_where=sa.text("provider = 'google_drive_sa'"),
    )
    op.create_table(
        "drive_folder_links",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "data_source_id",
            sa.Uuid(),
            sa.ForeignKey("data_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_folder_id",
            sa.Uuid(),
            sa.ForeignKey("workspace_folders.id", ondelete="SET NULL"),
        ),
        sa.Column("external_folder_id", sa.String(128), nullable=False),
        sa.Column("folder_name", sa.String(512), nullable=False),
        sa.Column("is_shared_drive", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(24), nullable=False, server_default="verified"),
        sa.Column(
            "verified_via", sa.String(32), nullable=False, server_default="visible_to_org_robot"
        ),
        sa.Column("shared_by_email", sa.String(320)),
        sa.Column("shared_at", sa.DateTime(timezone=True)),
        sa.Column("blocked_download_count", sa.Integer(), nullable=False, server_default="0"),
        *[
            sa.Column(name, sa.DateTime(timezone=True))
            for name in ("suspect_since", "access_lost_at", "purge_after", "last_checked_at")
        ],
        sa.Column("last_error_code", sa.String(40)),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "organization_id", "external_folder_id", name="uq_drive_folder_links_org_folder"
        ),
        sa.CheckConstraint(
            "status IN ('pending','verified','suspect','access_lost','purge_scheduled','removed')",
            name="ck_drive_folder_link_status",
        ),
        sa.CheckConstraint(
            "verified_via = 'visible_to_org_robot'", name="ck_drive_folder_link_explicit_share"
        ),
    )
    for column in ("organization_id", "data_source_id", "external_folder_id", "purge_after"):
        op.create_index("ix_drive_folder_links_" + column, "drive_folder_links", [column])
    # Terminal retirement and immutable org assignment: prohibit manual pool recycling too.
    op.execute("""CREATE FUNCTION google_sa_preserve_assignment() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF (OLD.organization_id IS NOT NULL AND NEW.organization_id IS DISTINCT FROM OLD.organization_id)
         OR (OLD.status IN ('retired','compromised') AND NEW.status IS DISTINCT FROM OLD.status) THEN
        RAISE EXCEPTION 'robot assignment is permanent';
      END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        "CREATE TRIGGER google_sa_preserve_assignment BEFORE UPDATE ON google_sa_identities FOR EACH ROW EXECUTE FUNCTION google_sa_preserve_assignment()"
    )


def downgrade():
    op.execute("DROP TRIGGER google_sa_preserve_assignment ON google_sa_identities")
    op.execute("DROP FUNCTION google_sa_preserve_assignment()")
    op.drop_table("drive_folder_links")
    op.drop_index("uq_data_sources_google_sa_org", table_name="data_sources")
    op.drop_constraint("data_sources_sa_identity_id_fkey", "data_sources", type_="foreignkey")
    op.drop_column("data_sources", "sa_identity_id")
    op.drop_table("google_sa_identities")
    op.drop_table("google_sa_projects")
