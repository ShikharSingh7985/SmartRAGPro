"""Retain source associations for deletion after changing active scope."""

import sqlalchemy as sa
from alembic import op

revision = "20261106_scope_provenance"
down_revision = "20261106_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("conversation_documents") as batch:
        batch.add_column(
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true())
        )


def downgrade() -> None:
    with op.batch_alter_table("conversation_documents") as batch:
        batch.drop_column("active")
