"""Add durable multimodal metadata, preserving the Phase 1 baseline."""

import sqlalchemy as sa
from alembic import op

revision = "20261106_multimodal"
down_revision = "3f9e7d07d878"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("content_hash", sa.String(64)))
        batch.add_column(
            sa.Column("extraction_mode", sa.String(30), nullable=False, server_default="auto")
        )
        for name in ["chunk_count", "table_count", "figure_count"]:
            batch.add_column(sa.Column(name, sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("index_fingerprint", sa.String(64)))
        batch.add_column(sa.Column("index_collection", sa.String(255)))
        batch.add_column(sa.Column("active_run", sa.String(36)))
        batch.create_unique_constraint(
            "uq_owned_content_mode", ["user_id", "content_hash", "extraction_mode"]
        )
    with op.batch_alter_table("ingestion_jobs") as batch:
        batch.add_column(sa.Column("stage", sa.String(30), nullable=False, server_default="queued"))
        for name in ["pages_processed", "total_pages"]:
            batch.add_column(sa.Column(name, sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(
            sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(
            sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch.add_column(sa.Column("run_token", sa.String(36)))
        batch.add_column(sa.Column("vector_collection", sa.String(255)))
        batch.add_column(sa.Column("dispatched_at", sa.DateTime(timezone=True)))
    op.create_table(
        "page_extractions",
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("page", sa.Integer(), primary_key=True),
        sa.Column("strategy", sa.String(40), nullable=False),
        sa.Column("quality", sa.JSON(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "document_assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("object_key", sa.String(512), unique=True, nullable=False),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("model_derived", sa.Boolean(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
    )
    op.create_index("ix_document_assets_document_id", "document_assets", ["document_id"])


def downgrade() -> None:
    op.drop_table("document_assets")
    op.drop_table("page_extractions")
    with op.batch_alter_table("ingestion_jobs") as batch:
        for name in [
            "stage",
            "pages_processed",
            "total_pages",
            "cancel_requested",
            "retryable",
            "run_token",
            "vector_collection",
            "dispatched_at",
        ]:
            batch.drop_column(name)
    with op.batch_alter_table("documents") as batch:
        batch.drop_constraint("uq_owned_content_mode", type_="unique")
        for name in [
            "content_hash",
            "extraction_mode",
            "chunk_count",
            "table_count",
            "figure_count",
            "index_fingerprint",
            "index_collection",
            "active_run",
        ]:
            batch.drop_column(name)
