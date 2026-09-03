from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.authz import authorize
from app.auth.dependencies import CurrentUserId
from app.auth.roles import Role
from app.auth.tickets import issue
from app.config import get_settings
from app.database.database import get_db
from app.database.schemas import Document
from app.validation.models import (
    DocumentCreate,
    DocumentResponse,
    TicketResponse,
)

router = APIRouter(prefix="/docs", tags=["documents"])
settings = get_settings()


@router.post("",status_code=status.HTTP_201_CREATED,response_model=DocumentResponse)
def create_document(data: DocumentCreate,user_id: CurrentUserId,db: Session = Depends(get_db)) -> Document:
    try:
        document = Document(title=data.title, owner_id=user_id)
        db.add(document)
        db.commit()
        db.refresh(document)
        return document
    except:
        db.rollback()
        raise


@router.post("/{doc_id}/ticket", response_model=TicketResponse)
def mint_ticket(doc_id: str,user_id: CurrentUserId,db: Session = Depends(get_db)) -> TicketResponse:
 
    role = authorize(user_id, doc_id, db)
    if role is Role.NONE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized for this document",
        )

    ticket, expires_at = issue(
        user_id=str(user_id),
        doc_id=str(doc_id),
        role=role,
        secret=settings.secret_key,
        ttl_seconds=settings.ticket_ttl_seconds,
    )

    return TicketResponse(ticket=ticket, expires_at=expires_at)

