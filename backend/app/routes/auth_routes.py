from fastapi import APIRouter, Cookie, Depends, Response, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.database import get_db
from app.services.auth_service import signin_service, signup_service
from app.services.token_service import (
    create_access_token,
    revoke_refresh_token,
    validate_refresh_in_db,
)
from app.validation.models import AccessTokenResponse, SigninRequest, SignupRequest

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

REFRESH_COOKIE = "refresh_token"
REFRESH_COOKIE_PATH = "/auth"


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=token,
        httponly=True,                
        secure=not settings.is_dev,    
        samesite="strict",
        path=REFRESH_COOKIE_PATH,
        max_age=settings.refresh_token_expire_days * 24 * 3600,
    )


@router.post(
    "/signup",
    status_code=status.HTTP_201_CREATED,
    response_model=AccessTokenResponse,
)
def signup(
    data: SignupRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> AccessTokenResponse:
    access_token, refresh_token = signup_service(data, db)
    _set_refresh_cookie(response, refresh_token)
    return AccessTokenResponse(access_token=access_token)


@router.post(
    "/signin",
    status_code=status.HTTP_200_OK,
    response_model=AccessTokenResponse,
)
def signin(
    data: SigninRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> AccessTokenResponse:
    access_token, refresh_token = signin_service(data, db)
    _set_refresh_cookie(response, refresh_token)
    return AccessTokenResponse(access_token=access_token)


@router.post(
    "/refresh",
    status_code=status.HTTP_200_OK,
    response_model=AccessTokenResponse,
)
def refresh(
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
    db: Session = Depends(get_db),
) -> AccessTokenResponse:
    user_id = validate_refresh_in_db(refresh_token, db)
    return AccessTokenResponse(access_token=create_access_token(user_id))


@router.post("/signout", status_code=status.HTTP_204_NO_CONTENT)
def signout(
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
    db: Session = Depends(get_db),
) -> Response:
    revoke_refresh_token(refresh_token, db)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)
    return response
