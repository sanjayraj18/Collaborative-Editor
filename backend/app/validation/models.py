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

    access_token: str
    token_type: str = "bearer"


class DocumentCreate(BaseModel):
    title : str = Field(min_length = 1, max_length = 100)


class DocumentResponse(BaseModel): 
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    owner_id: UUID
    created_at: datetime

class TicketResponse(BaseModel):
    ticket: str
    expires_at: int

