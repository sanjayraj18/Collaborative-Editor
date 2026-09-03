from typing import Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials,HTTPBearer
from services.token_service import verify_access_token
from sqlalchemy.orm import Session
from database.database import get_db
from database.schemas import User


bearer_scheme = HTTPBearer(auto_error=False)

def get_current_user_id(credentials : Annotated[HTTPAuthorizationCredentials | None ,  Depends(bearer_scheme)]):
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail = "Not authenticated",
            headers={"WWW-Authenticate" : "Bearer"}
        )

    return verify_access_token(credentials.credentials)


def get_current_user(user_id : Annotated[str, Depends(get_current_user_id)] , db : Annotated[Session, Depends(get_db)]):

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

CurrentUserId = Annotated[str, Depends(get_current_user_id)]
Currentuser  = Annotated[User, Depends(get_current_user)]