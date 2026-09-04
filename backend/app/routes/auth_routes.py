from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUserId
from app.auth.ratelimit import clear_login_rate_limit, enforce_login_rate_limit
from app.config import get_settings
from app.database.database import get_db
from app.services.auth_service import signin_service, signup_service
from app.services.token_service import (
    create_access_token,
    revoke_refresh_token,
    revoke_user_tokens,
    rotate_refresh_token,
)
from app.validation.models import AccessTokenResponse, SigninRequest, SignupRequest

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

REFRESH_COOKIE = "refresh_token"
REFRESH_COOKIE_PATH = "api/auth"


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
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AccessTokenResponse:

    enforce_login_rate_limit(request, data.email)
    access_token, refresh_token = signin_service(data, db)
    clear_login_rate_limit(data.email)
    _set_refresh_cookie(response, refresh_token)
    return AccessTokenResponse(access_token=access_token)


@router.post(
    "/refresh",
    status_code=status.HTTP_200_OK,
    response_model=AccessTokenResponse,
)
def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
    db: Session = Depends(get_db),
) -> AccessTokenResponse:

    user_id, new_refresh_token = rotate_refresh_token(refresh_token, db)
    _set_refresh_cookie(response, new_refresh_token)
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


@router.post("/signout-all", status_code=status.HTTP_204_NO_CONTENT)
def signout_all(
    user_id: CurrentUserId,
    db: Session = Depends(get_db),
) -> Response:

    revoke_user_tokens(user_id, db)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)
    return response
