from pydantic import BaseModel, Field, EmailStr
from Datetime import datetime
from uuid import UUID


class UserBase(BaseModel):  
    name: str = Field(default = None , min_length=4, max_length=25)
    email: EmailStr = Field(default = None) 
    password: str = Field(default = None, min_length = 6, max_length = 100)

class UserResponse(BaseModel):
    id : UUID
    name : str
    email : EmailStr
    created_at : datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token : str
    refresh_token : str
    token_type: str = "bearer"

class TokenData(BaseModel):
    user_id : UUID
    exp : int


class RefreshRequest(BaseModel):
    refresh_token : str