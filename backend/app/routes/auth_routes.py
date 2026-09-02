from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.database import get_db
from validation.models import UserBase
from services.auth_service import signin_service, signup_service

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post('/signin',status_code=status.HTTP_200_OK)
async def signin(data : UserBase,db :Session = Depends(get_db)):
    return signin_service(data, db)

@router.post('/signup',status_code=status.HTTP_201_CREATED)
async def signup(data : UserBase,db :Session = Depends(get_db)):
    return signup_service(data, db)

@router.post('/signout',status_code=status.HTTP_200_OK)
async def signout(data : UserBase,db :Session = Depends(get_db)):
    return {"message": "Sign out endpoint"}

@router.post('/refresh',status_code=status.HTTP_200_OK)    
async def refresh(db :Session = Depends(get_db)):
    return {"message": "Refresh token endpoint"}