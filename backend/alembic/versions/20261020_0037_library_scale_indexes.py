"""Library scale indexes (spike M4/M6): trigram search on node names and file lookup without a nested loop.

PostgreSQL only; SQLite (unit tests) has neither ``pg_trgm`` nor a use for these indexes. ``CONCURRENTLY`` keeps
writes flowing on a live database, which needs the statements outside the migration transaction.
"""

from alembic import op

revision = "20261020_0037"
down_revision = "20261019_0036"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    with op.get_context().autocommit_block():
        # `@` mentions and the library name search: lower(name) LIKE '%q%' (T1, T5)
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_library_nodes_name_trgm "
                   "ON library_nodes USING gin (lower(name) gin_trgm_ops)")
        # lookup of a file across scopes without scanning every scope (T4)
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_documents_organization_external_file "
                   "ON documents (organization_id, external_file_id)")


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_documents_organization_external_file")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_library_nodes_name_trgm")
