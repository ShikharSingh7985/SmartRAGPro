"""Durable trace propagation and worker heartbeats."""

import sqlalchemy as sa
from alembic import op

revision = "20261108_operations"
down_revision = "20261107_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ingestion_jobs") as batch:
        batch.add_column(sa.Column("trace_parent", sa.String(55), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("ingestion_jobs") as batch:
        batch.drop_column("trace_parent")
