"""Expand embeddings with a nullable vector; retain legacy JSON for rollback."""
import sqlalchemy as sa

from alembic import op

revision = '20260930_0019'
down_revision = '20260929_0018'
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('CREATE EXTENSION IF NOT EXISTS vector')
        op.execute('ALTER TABLE document_chunks ADD COLUMN embedding_vec vector(1536)')
    else:
        op.add_column('document_chunks', sa.Column('embedding_vec', sa.JSON()))


def downgrade():
    op.drop_column('document_chunks', 'embedding_vec')
