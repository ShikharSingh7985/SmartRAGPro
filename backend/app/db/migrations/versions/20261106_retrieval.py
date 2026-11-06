"""Persistent tenant-scoped BM25 chunk and inverted term index."""

import sqlalchemy as sa
from alembic import op

revision = "20261106_retrieval"
down_revision = "20261106_scope_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("run_token", sa.String(36), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("length", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
    )
    op.create_index("ix_search_scope", "search_chunks", ["user_id", "document_id", "run_token"])
    op.create_table(
        "search_terms",
        sa.Column(
            "chunk_id",
            sa.Uuid(),
            sa.ForeignKey("search_chunks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("term", sa.String(80), primary_key=True),
        sa.Column("frequency", sa.Integer(), nullable=False),
    )
    op.create_index("ix_search_term", "search_terms", ["term", "chunk_id"])


def downgrade() -> None:
    op.drop_table("search_terms")
    op.drop_table("search_chunks")
