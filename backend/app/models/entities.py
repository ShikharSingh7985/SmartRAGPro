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
    __table_args__ = (
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


class ConversationDocument(Base):
    __tablename__ = "conversation_documents"
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
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
    __table_args__ = (
        UniqueConstraint("conversation_id", "request_id", "role"),
        UniqueConstraint("conversation_id", "position"),
        CheckConstraint("role IN ('user', 'assistant')", name="ck_message_role"),
    )
