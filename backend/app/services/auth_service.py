from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.passwords import DUMMY_HASH, hash_password, verify_password
from app.database.schemas import User
from app.services.token_service import (
    create_access_token,
    create_refresh_token,
    issue_refresh_token
)
from app.validation.models import SigninRequest, SignupRequest


INVALID_CREDENTIALS = "Invalid email or password"

def email_exists(email: str, db: Session) -> bool:
    return db.query(User).filter(User.email == email).first() is not None



def signin_service(data: SigninRequest, db: Session) -> tuple[str, str]:
    user = db.query(User).filter(User.email == data.email).first()

    stored = user.password if user is not None else DUMMY_HASH
    password_ok = verify_password(data.password, stored)

    if user is None or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=INVALID_CREDENTIALS,
        )

    access_token = create_access_token(user.id)
    return access_token, issue_refresh_token(user.id, db)


def signup_service(data: SignupRequest, db: Session) -> tuple[str, str]:
    if email_exists(data.email, db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(
        name=data.name,
        email=data.email,
        password=hash_password(data.password),
    )
    db.add(user)
    
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        ) from None
    db.refresh(user)

    access_token = create_access_token(user.id)
    return access_token, issue_refresh_token(user.id, db)
