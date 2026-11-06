import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Identity:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class User(Identity, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    token_version: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Document(Identity, Base):
    __tablename__ = "documents"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    page_count: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(String(255))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    extraction_mode: Mapped[str] = mapped_column(String(30), default="auto")
    chunk_count: Mapped[int] = mapped_column(default=0)
    table_count: Mapped[int] = mapped_column(default=0)
    figure_count: Mapped[int] = mapped_column(default=0)
    index_fingerprint: Mapped[str | None] = mapped_column(String(64))
    index_collection: Mapped[str | None] = mapped_column(String(255))
    active_run: Mapped[str | None] = mapped_column(String(36))
    size_bytes: Mapped[int] = mapped_column(default=0)
    derived_bytes: Mapped[int] = mapped_column(default=0)
    __table_args__ = (
        UniqueConstraint(
            "user_id", "content_hash", "extraction_mode", name="uq_owned_content_mode"
        ),
        CheckConstraint(
            "status IN ('uploading', 'queued', 'ready', 'failed', 'deleting')",
            name="ck_document_status",
        ),
    )


class IngestionJob(Identity, Base):
    __tablename__ = "ingestion_jobs"
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20), default="ingest")
    status: Mapped[str] = mapped_column(String(20), default="queued")
    attempts: Mapped[int] = mapped_column(default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    error: Mapped[str | None] = mapped_column(String(255))
    stage: Mapped[str] = mapped_column(String(30), default="queued")
    pages_processed: Mapped[int] = mapped_column(default=0)
    total_pages: Mapped[int] = mapped_column(default=0)
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    run_token: Mapped[str | None] = mapped_column(String(36))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retryable: Mapped[bool] = mapped_column(default=True)
    vector_collection: Mapped[str | None] = mapped_column(String(255))
    __table_args__ = (
        Index("ix_jobs_claim", "status", "available_at"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_job_status"
        ),
        CheckConstraint("kind IN ('ingest', 'delete', 'cleanup')", name="ck_job_kind"),
    )


class Conversation(Identity, Base):
    __tablename__ = "conversations"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(120), default="New conversation")
    scope_version: Mapped[int] = mapped_column(default=1)
    active_topic: Mapped[str] = mapped_column(Text, default="")
    references: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_warning: Mapped[str | None] = mapped_column(String(255))


class ConversationDocument(Base):
    __tablename__ = "conversation_documents"
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    active: Mapped[bool] = mapped_column(default=True)
    __table_args__ = (Index("ix_conversation_documents_document", "document_id"),)


class Message(Identity, Base):
    __tablename__ = "messages"
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    position: Mapped[int] = mapped_column()
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    turn_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    __table_args__ = (
        UniqueConstraint("conversation_id", "request_id", "role"),
        UniqueConstraint("conversation_id", "position"),
        CheckConstraint("role IN ('user', 'assistant')", name="ck_message_role"),
    )


class PageExtraction(Base):
    __tablename__ = "page_extractions"
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    page: Mapped[int] = mapped_column(primary_key=True)
    strategy: Mapped[str] = mapped_column(String(40))
    quality: Mapped[dict[str, Any]] = mapped_column(JSON)
    content: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DocumentAsset(Identity, Base):
    __tablename__ = "document_assets"
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    page: Mapped[int] = mapped_column()
    kind: Mapped[str] = mapped_column(String(20))
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    caption: Mapped[str] = mapped_column(Text, default="")
    available: Mapped[bool] = mapped_column(default=False)
    model_derived: Mapped[bool] = mapped_column(default=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ConversationSummary(Base):
    __tablename__ = "conversation_summaries"
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True
    )
    covered_through: Mapped[int] = mapped_column(default=0)
    version: Mapped[int] = mapped_column(default=0)
    content: Mapped[str] = mapped_column(Text, default="")
    provenance: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class SearchChunk(Base):
    __tablename__ = "search_chunks"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    run_token: Mapped[str] = mapped_column(String(36))
    page: Mapped[int] = mapped_column()
    length: Mapped[int] = mapped_column()
    text: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSON)
    __table_args__ = (Index("ix_search_scope", "user_id", "document_id", "run_token"),)


class SearchTerm(Base):
    __tablename__ = "search_terms"
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("search_chunks.id", ondelete="CASCADE"), primary_key=True
    )
    term: Mapped[str] = mapped_column(String(80), primary_key=True)
    frequency: Mapped[int] = mapped_column()
    __table_args__ = (Index("ix_search_term", "term", "chunk_id"),)


class RefreshToken(Identity, Base):
    __tablename__ = "refresh_tokens"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    digest: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SecurityInspection(Identity, Base):
    __tablename__ = "security_inspections"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    object_id: Mapped[str] = mapped_column(String(128))
    stage: Mapped[str] = mapped_column(String(20))
    policy_version: Mapped[str] = mapped_column(String(30))
    decision: Mapped[str] = mapped_column(String(20))
    score: Mapped[int] = mapped_column()
    reasons: Mapped[list[str]] = mapped_column(JSON)
    __table_args__ = (UniqueConstraint("document_id", "object_id", "stage", "policy_version"),)


class AuditEvent(Identity, Base):
    __tablename__ = "audit_events"
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    event: Mapped[str] = mapped_column(String(50))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    __table_args__ = (Index("ix_audit_retention", "created_at"),)
