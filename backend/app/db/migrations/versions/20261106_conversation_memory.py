"""Persistent conversational context and incremental summary provenance."""

import sqlalchemy as sa
from alembic import op

revision = "20261106_conversations"
down_revision = "20261106_multimodal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(
            sa.Column("scope_version", sa.Integer(), nullable=False, server_default="1")
        )
        batch.add_column(sa.Column("active_topic", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("references", sa.JSON(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("source_warning", sa.String(255)))
    with op.batch_alter_table("messages") as batch:
        batch.add_column(sa.Column("turn_metadata", sa.JSON(), nullable=False, server_default="{}"))
    op.create_table(
        "conversation_summaries",
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("covered_through", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_messages_search ON messages USING gin (to_tsvector('simple', content))"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_messages_search")
    op.drop_table("conversation_summaries")
    with op.batch_alter_table("messages") as batch:
        batch.drop_column("turn_metadata")
    with op.batch_alter_table("conversations") as batch:
        for name in ["scope_version", "active_topic", "references", "source_warning"]:
            batch.drop_column(name)
