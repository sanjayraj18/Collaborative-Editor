import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.schemas import RefreshToken

settings = get_settings()

JWT_ISSUER = "collab"
JWT_AUDIENCE = "collab-api"
REFRESH_TOKEN_BYTES = 32


def _unauthorized() -> HTTPException:
    """One message for every failure: no oracle for the caller."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def create_access_token(user_id: UUID | str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int(
            (now + timedelta(minutes=settings.access_token_expire_minutes)).timestamp()
        ),
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def verify_access_token(token: str) -> str:
    if not token:
        raise _unauthorized()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            issuer=JWT_ISSUER,
            audience=JWT_AUDIENCE,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
    except jwt.PyJWTError:
        raise _unauthorized() from None

    user_id = payload.get("sub")
    if not user_id:
        raise _unauthorized()
    return str(user_id)


def create_refresh_token() -> str:
    """Opaque and random. Nothing to parse, nothing to forge, nothing to leak."""
    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def save_refresh_to_db(user_id: UUID | str, refresh_token: str, db: Session) -> None:
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_expire_days
    )
    db.add(
        RefreshToken(
            user_id=user_id,
            token_hash=hash_refresh_token(refresh_token),
            expires_at=expires_at,
        )
    )
    db.commit()


def validate_refresh_in_db(token: str | None, db: Session) -> str:
    if not token:
        raise _unauthorized()

    row = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == hash_refresh_token(token))
        .first()
    )
    if row is None:
        raise _unauthorized()

    if row.expires_at <= datetime.now(timezone.utc):
        db.delete(row)
        db.commit()
        raise _unauthorized()

    return str(row.user_id)


def revoke_refresh_token(token: str | None, db: Session) -> None:
    if not token:
        return
    db.query(RefreshToken).filter(
        RefreshToken.token_hash == hash_refresh_token(token)
    ).delete()
    db.commit()
