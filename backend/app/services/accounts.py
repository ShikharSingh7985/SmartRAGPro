"""Revoke first, purge conversations, then durably remove storage before the owner."""

import secrets
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.conversations.checkpoints import clear_checkpoint
from backend.app.core.security import hasher
from backend.app.models.entities import (
    AuditEvent,
    Conversation,
    Document,
    IngestionJob,
    RefreshToken,
    User,
    now,
)
from backend.app.services.sessions import revoke


def delete_account(db: Session, user: User) -> None:
    user.is_active, user.deleted_at = False, now()
    revoke(db, user, "account_deleted")
    user.email = f"deleted-{user.id}@invalid.local"
    user.password_hash = hasher.hash(secrets.token_urlsafe(48))
    for conversation in db.scalars(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.id)
        .with_for_update()
    ):
        clear_checkpoint(db, conversation)
        db.delete(conversation)
    for document in db.scalars(
        select(Document).where(Document.user_id == user.id).order_by(Document.id).with_for_update()
    ):
        document.status = "deleting"
        db.add(IngestionJob(document_id=document.id, kind="delete"))
    db.commit()


def maintain_security(db: Session, retention_days: int = 90) -> None:
    cutoff = now() - timedelta(days=retention_days)
    db.execute(delete(AuditEvent).where(AuditEvent.created_at < cutoff))
    # Keep consumed tokens until expiry so reuse is detectable throughout their lifetime.
    db.execute(delete(RefreshToken).where(RefreshToken.expires_at < now()))
    for user in db.scalars(
        select(User)
        .where(
            User.deleted_at.is_not(None),
            ~select(Document.id).where(Document.user_id == User.id).exists(),
        )
        .with_for_update(skip_locked=True)
        .limit(100)
    ):
        db.delete(user)
    db.commit()
