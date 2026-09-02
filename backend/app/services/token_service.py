from fastapi import HTTPException, status
from jose import jwt, JWTError
from config import settings
from datetime import timedelta, timezone, datetime
from sqlalchemy.orm import Session 
from database.schemas import RefreshToken


def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode = {
        "user_id": str(user_id),
        "exp": int(expire.timestamp())
    }

    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    return encoded_jwt


def verify_access_token(token : str) -> str:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_id = payload.get("user_id")

        if not user_id:
           raise HTTPException(status_code=401, detail="Invalid token")
        
        return user_id
    
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def create_refresh_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    to_encode = {
        "user_id": str(user_id),
        "exp": int(expire.timestamp())
    }

    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    return encoded_jwt


def verify_refresh_token(token: str) -> str:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        return user_id
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def save_refresh_to_db(user_id : str, refresh_token : str, db : Session) -> None:
    try:
        expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        db_refresh_token = RefreshToken(
            user_id = user_id,
            token = refresh_token,
            expires_at = expire
        )

        db.add(db_refresh_token)
        db.commit()

    except Exception:
        db.rollback()
        raise


def validate_refresh_in_db(token : str, db :Session) -> str:
    user_id = verify_refresh_token(token)

    db_token = db.query(RefreshToken).filter(
        RefreshToken.token == token
    ).first()

    if not db_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token not found or revoked"
        )

    if datetime.now(timezone.utc) > db_token.expires_at:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expired"
        )

    return user_id