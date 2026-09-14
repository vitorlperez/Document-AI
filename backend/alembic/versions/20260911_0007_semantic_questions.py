"""Store local chunk embeddings for folder-scoped semantic retrieval."""

import sqlalchemy as sa

from alembic import op

revision = "20260911_0007"
down_revision = "20260911_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_chunks", sa.Column("embedding", sa.JSON()))
    op.add_column("document_chunks", sa.Column("embedding_model", sa.String(80)))


def downgrade() -> None:
    op.drop_column("document_chunks", "embedding_model")
    op.drop_column("document_chunks", "embedding")
