from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.auth.roles import Role, Visibility


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
    access_token: str
    token_type: str = "bearer"


class DocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    visibility: Visibility = Visibility.PRIVATE


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    visibility: Visibility | None = None


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    owner_id: UUID
    visibility: Visibility
    role: Role
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, document, role: Role) -> "DocumentResponse":
        return cls(
            id=document.id,
            title=document.title,
            owner_id=document.owner_id,
            visibility=document.visibility,
            role=role,
            created_at=document.created_at,
            updated_at=document.updated_at,
        )


class MemberCreate(BaseModel):
    email: EmailStr
    role: Literal["reader", "writer"]


class MemberResponse(BaseModel):
    user_id: UUID
    email: EmailStr
    name: str
    role: Role
    created_at: datetime

    @classmethod
    def of(cls, member, user) -> "MemberResponse":
        return cls(
            user_id=user.id,
            email=user.email,
            name=user.name,
            role=Role(member.role),
            created_at=member.created_at,
        )


class TicketResponse(BaseModel):
    ticket: str
    expires_at: int
