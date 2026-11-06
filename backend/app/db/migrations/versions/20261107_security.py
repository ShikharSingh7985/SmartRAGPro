"""Refresh rotation, account lifecycle, upload quotas and content-security audit."""

import sqlalchemy as sa
from alembic import op

revision = "20261107_security"
down_revision = "20261106_retrieval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True)))
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(
            sa.Column("derived_bytes", sa.Integer(), nullable=False, server_default="0")
        )
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])
    op.create_table(
        "security_inspections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("object_id", sa.String(128), nullable=False),
        sa.Column("stage", sa.String(20), nullable=False),
        sa.Column("policy_version", sa.String(30), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.UniqueConstraint("document_id", "object_id", "stage", "policy_version"),
    )
    op.create_index("ix_security_inspections_user_id", "security_inspections", ["user_id"])
    op.create_index("ix_security_inspections_document_id", "security_inspections", ["document_id"])
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("event", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.Uuid()),
    )
    op.create_index("ix_audit_events_actor_id", "audit_events", ["actor_id"])
    op.create_index("ix_audit_retention", "audit_events", ["created_at"])


def downgrade() -> None:
    for table in ["audit_events", "security_inspections", "refresh_tokens"]:
        op.drop_table(table)
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("derived_bytes")
        batch.drop_column("size_bytes")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("deleted_at")
        batch.drop_column("is_active")
