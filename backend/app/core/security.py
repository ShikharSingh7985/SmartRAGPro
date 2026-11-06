from datetime import timedelta
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.app.core.config import Settings, get_settings
from backend.app.db.session import get_db
from backend.app.models.entities import User, now

hasher = PasswordHasher()
dummy_hash = hasher.hash("timing-equalization-non-user-password")
bearer = HTTPBearer(auto_error=False)


def verify_password(password: str, stored: str) -> bool:
    try:
        return hasher.verify(stored, password)
    except (VerificationError, InvalidHashError):
        return False


def issue_token(user: User, settings: Settings) -> str:
    issued = now()
    return jwt.encode(
        {
            "sub": str(user.id),
            "ver": user.token_version,
            "jti": str(uuid4()),
            "iat": issued,
            "nbf": issued,
            "exp": issued + timedelta(minutes=settings.access_token_minutes),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "type": "access",
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    try:
        if not credentials:
            raise ValueError("missing token")
        claims = jwt.decode(
            credentials.credentials,
            settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require": ["sub", "ver", "jti", "iat", "nbf", "exp", "iss", "aud", "type"]},
        )
        user = db.get(User, UUID(claims["sub"]))
        UUID(claims["jti"])
        if (
            not user
            or not user.is_active
            or user.deleted_at
            or type(claims["ver"]) is not int
            or user.token_version != claims["ver"]
            or claims["type"] != "access"
        ):
            raise ValueError("revoked token")
        return user
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(
            401, "Valid authentication required", headers={"WWW-Authenticate": "Bearer"}
        ) from exc
