"""Add the provider-neutral Company Library projection and backfill indexed files."""

from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import context, op


revision = "20260913_0012"
down_revision = "20260912_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "library_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=True),
        sa.Column("source_url", sa.String(2048), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["data_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["library_nodes.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_library_nodes_organization_id", "library_nodes", ["organization_id"])
    op.create_index("ix_library_nodes_source_id", "library_nodes", ["source_id"])
    op.create_index("ix_library_nodes_parent_id", "library_nodes", ["parent_id"])
    op.create_index("uq_library_nodes_source_external", "library_nodes", ["source_id", "external_id"], unique=True)
    op.create_index("ix_library_nodes_organization_parent", "library_nodes", ["organization_id", "parent_id"])

    if context.is_offline_mode():
        _offline_backfill()
        return
    _online_backfill()


def _offline_backfill() -> None:
    op.execute(
        """
        WITH roots AS (
          INSERT INTO library_nodes (id, organization_id, source_id, parent_id, external_id, kind, name, created_at)
          SELECT md5('library-source:' || sources.id::text)::uuid, sources.organization_id, sources.id, NULL,
                 '__company_library_source_root__', 'source',
                 CASE WHEN sources.provider = 'google_drive' THEN 'Google Drive' ELSE initcap(replace(sources.provider, '_', ' ')) END,
                 now()
          FROM data_sources AS sources
          WHERE EXISTS (
            SELECT 1 FROM documents AS documents
            JOIN workspace_folders AS folders ON folders.id = documents.workspace_folder_id
            WHERE folders.source_id = sources.id AND documents.index_status = 'indexed'
          )
          RETURNING id, source_id
        )
        INSERT INTO library_nodes (id, organization_id, source_id, parent_id, external_id, kind, name, mime_type, source_url, created_at)
        SELECT md5('library-file:' || item.source_id::text || ':' || item.external_file_id)::uuid,
               item.organization_id, item.source_id, roots.id, item.external_file_id,
               'file', item.name, item.mime_type, item.source_url, now()
        FROM (
          SELECT DISTINCT ON (folders.source_id, documents.external_file_id)
                 documents.organization_id, folders.source_id, documents.external_file_id,
                 documents.name, documents.mime_type, documents.source_url
          FROM documents
          JOIN workspace_folders AS folders ON folders.id = documents.workspace_folder_id
          WHERE documents.index_status = 'indexed'
          ORDER BY folders.source_id, documents.external_file_id, documents.id
        ) AS item
        JOIN roots ON roots.source_id = item.source_id
        """
    )


def _online_backfill() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT DISTINCT ON (folders.source_id, documents.external_file_id)
                documents.organization_id, folders.source_id, sources.provider,
                documents.external_file_id, documents.name, documents.mime_type, documents.source_url
            FROM documents
            JOIN workspace_folders AS folders ON folders.id = documents.workspace_folder_id
            JOIN data_sources AS sources ON sources.id = folders.source_id
            WHERE documents.index_status = 'indexed'
            ORDER BY folders.source_id, documents.external_file_id, documents.id
            """
        )
    ).mappings()
    roots: dict[object, object] = {}
    for row in rows:
        source_id = row["source_id"]
        root_id = roots.get(source_id)
        if root_id is None:
            root_id = uuid4()
            roots[source_id] = root_id
            provider_name = "Google Drive" if row["provider"] == "google_drive" else str(row["provider"]).replace("_", " ").title()
            bind.execute(
                sa.text(
                    """INSERT INTO library_nodes
                    (id, organization_id, source_id, parent_id, external_id, kind, name, created_at)
                    VALUES (:id, :organization_id, :source_id, NULL, :external_id, 'source', :name, now())"""
                ),
                {"id": root_id, "organization_id": row["organization_id"], "source_id": source_id, "external_id": "__company_library_source_root__", "name": provider_name},
            )
        bind.execute(
            sa.text(
                """INSERT INTO library_nodes
                (id, organization_id, source_id, parent_id, external_id, kind, name, mime_type, source_url, created_at)
                VALUES (:id, :organization_id, :source_id, :parent_id, :external_id, 'file', :name, :mime_type, :source_url, now())"""
            ),
            {
                "id": uuid4(), "organization_id": row["organization_id"], "source_id": source_id, "parent_id": root_id,
                "external_id": row["external_file_id"], "name": row["name"], "mime_type": row["mime_type"], "source_url": row["source_url"],
            },
        )


def downgrade() -> None:
    op.drop_table("library_nodes")
