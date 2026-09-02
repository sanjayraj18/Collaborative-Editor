from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SignupRequest(BaseModel):
    name: str = Field(min_length=4, max_length=25)
    email: EmailStr
    password: str = Field(min_length=6, max_length=100)


class SigninRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=100)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: EmailStr
    created_at: datetime


class AccessTokenResponse(BaseModel):
    """The refresh token is NOT here: it goes out as an HttpOnly cookie."""

    access_token: str
    token_type: str = "bearer"
