import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

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


def _now() -> datetime:
    return datetime.now(UTC)


def create_access_token(user_id: UUID | str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_expire_minutes)).timestamp()),
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


def issue_refresh_token(user_id: str | UUID, db: Session, *, family_id: UUID | None = None):
    token = create_refresh_token()

    db.add(
        RefreshToken(
            user_id=user_id,
            token_hash=hash_refresh_token(token),
            family_id=family_id or uuid4(),
            expires_at=_now() + timedelta(days=settings.refresh_token_expire_days),
        )
    )

    db.commit()
    return token


def _revoke_family(family_id: UUID, db: Session):
    db.query(RefreshToken).filter(RefreshToken.family_id == family_id).delete()
    db.commit()


def rotate_refresh_token(token: str | None, db: Session) -> tuple[str, str]:

    if not token:
        raise _unauthorized()

    token_hash = hash_refresh_token(token)

    claimed = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == token_hash, RefreshToken.used_at.is_(None))
        .update({RefreshToken.used_at: _now()}, synchronize_session=False)
    )
    db.commit()

    row = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if row is None:
        raise _unauthorized()

    if claimed == 0:
        used_at = row.used_at or _now()
        if (_now() - used_at).total_seconds() > settings.refresh_reuse_grace_seconds:
            _revoke_family(row.family_id, db)
        raise _unauthorized()

    if row.expires_at <= _now():
        _revoke_family(row.family_id, db)
        raise _unauthorized()

    return str(row.user_id), issue_refresh_token(row.user_id, db, family_id=row.family_id)


def revoke_refresh_token(token: str | None, db: Session) -> None:
    if not token:
        return
    row = (
        db.query(RefreshToken).filter(RefreshToken.token_hash == hash_refresh_token(token)).first()
    )
    if row is None:
        return
    _revoke_family(row.family_id, db)


def revoke_user_tokens(user_id: UUID | str, db: Session) -> int:
    count = db.query(RefreshToken).filter(RefreshToken.user_id == user_id).delete()
    db.commit()
    return count
