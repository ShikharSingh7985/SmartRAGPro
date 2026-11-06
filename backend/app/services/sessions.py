"""Opaque, one-use refresh credentials. All mutations lock the owner first."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.core.security import issue_token
from backend.app.models.entities import AuditEvent, RefreshToken, User, now
from backend.app.schemas.api import TokenOut


def revoke(db: Session, user: User, event: str) -> None:
    user.token_version += 1
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user.id).values(revoked_at=now()))
    db.add(AuditEvent(actor_id=user.id, event=event))


def issue_pair(
    db: Session,
    user: User,
    settings: Settings,
    *,
    family: UUID | None = None,
    expires: datetime | None = None,
) -> TokenOut:
    selector = uuid4()
    token = f"{selector}.{secrets.token_urlsafe(48)}"
    db.add(
        RefreshToken(
            id=selector,
            user_id=user.id,
            family_id=family or uuid4(),
            digest=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=expires or now() + timedelta(days=settings.refresh_token_days),
        )
    )
    return TokenOut(
        access_token=issue_token(user, settings),
        refresh_token=token,
        expires_in=settings.access_token_minutes * 60,
    )


def rotate(db: Session, token: str, settings: Settings) -> TokenOut:
    failure = HTTPException(401, "Valid authentication required")
    try:
        selector = UUID(token.split(".", 1)[0])
    except (ValueError, AttributeError):
        raise failure from None
    candidate = db.get(RefreshToken, selector)
    digest = hashlib.sha256(token.encode()).hexdigest()
    if not candidate or not secrets.compare_digest(candidate.digest, digest):
        raise failure
    user = db.scalar(
        select(User)
        .where(User.id == candidate.user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    row = db.scalar(
        select(RefreshToken)
        .where(RefreshToken.id == selector)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not user or not user.is_active or user.deleted_at or not row:
        raise failure
    expiry = row.expires_at.replace(tzinfo=UTC) if row.expires_at.tzinfo is None else row.expires_at
    if row.revoked_at or expiry <= now():
        raise failure
    # A valid consumed credential is evidence of reuse; a guessed secret never revokes sessions.
    if row.consumed_at:
        revoke(db, user, "refresh_reuse")
        db.commit()
        raise failure
    row.consumed_at = now()
    result = issue_pair(db, user, settings, family=row.family_id, expires=expiry)
    db.add(AuditEvent(actor_id=user.id, event="refresh_rotated"))
    db.commit()
    return result
