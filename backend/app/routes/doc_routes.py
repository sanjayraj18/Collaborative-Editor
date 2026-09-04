from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.auth.authz import DocumentNotFound, authorize, role_for
from app.auth.dependencies import CurrentUserId
from app.auth.roles import Role
from app.auth.tickets import issue
from app.config import get_settings
from app.database.database import get_db
from app.database.schemas import Document, DocumentMember, User
from app.validation.models import (
    DocumentCreate,
    DocumentResponse,
    DocumentUpdate,
    MemberCreate,
    MemberResponse,
    TicketResponse,
)

router = APIRouter(prefix="/docs", tags=["documents"])
settings = get_settings()


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Document not found",
    )


def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not authorized for this document",
    )


def _resolve(doc_id: str, user_id: str, db: Session) -> tuple[Document, Role]:

    try:
        role = authorize(user_id, doc_id, db)
    except DocumentNotFound:
        raise _not_found() from None

    if role is Role.NONE:
        raise _forbidden()

    document = db.get(Document, UUID(str(doc_id)))
    if document is None:
        raise _not_found()

    return document, role


def _require_owner(doc_id: str, user_id: str, db: Session) -> Document:
    document, _ = _resolve(doc_id, user_id, db)
    if str(document.owner_id) != str(user_id):
        raise _forbidden()
    return document


@router.get("", response_model=list[DocumentResponse])
def list_document(user_id: CurrentUserId, db: Session = Depends(get_db)) -> list[DocumentResponse]:
    user_uuid = UUID(user_id)

    rows = (
        db.query(Document, DocumentMember.role)
        .outerjoin(
            DocumentMember,
            and_(DocumentMember.document_id == Document.id, DocumentMember.user_id == user_uuid),
        )
        .filter(
            or_(
                Document.owner_id == user_uuid,
                DocumentMember.user_id.isnot(None),
            )
        )
        .order_by(Document.updated_at.desc())
        .all()
    )

    return [
        DocumentResponse.of(document, role_for(document, user_uuid, member_role))
        for document, member_role in rows
    ]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=DocumentResponse)
def create_document(
    data: DocumentCreate, user_id: CurrentUserId, db: Session = Depends(get_db)
) -> DocumentResponse:
    document = Document(
        title=data.title,
        owner_id=UUID(user_id),
        visibility=data.visibility,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return DocumentResponse.of(document, Role.WRITER)


@router.get("/{doc_id}", response_model=DocumentResponse)
def get_document(
    doc_id: str, user_id: CurrentUserId, db: Session = Depends(get_db)
) -> DocumentResponse:
    document, role = _resolve(doc_id, user_id, db)
    return DocumentResponse.of(document, role)


@router.patch("/{doc_id}", response_model=DocumentResponse)
def update_document(
    doc_id: str, data: DocumentUpdate, user_id: CurrentUserId, db: Session = Depends(get_db)
) -> DocumentResponse:
    document = _require_owner(doc_id, user_id, db)
    changes = data.model_dump(exclude_unset=True)

    if "title" in changes:
        document.title = changes["title"]

    if "visibility" in changes and changes["visibility"] != document.visibility:
        document.visibility = changes["visibility"]
        document.permissions_version += 1

    db.commit()
    db.refresh(document)
    return DocumentResponse.of(document, Role.WRITER)


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    doc_id: str,
    user_id: CurrentUserId,
    db: Session = Depends(get_db),
) -> None:
    document = _require_owner(doc_id, user_id, db)
    db.delete(document)
    db.commit()
    # Phase 3: the room for this document must be drained and closed here.


@router.get("/{doc_id}/members", response_model=list[MemberResponse])
def list_members(
    doc_id: str, user_id: CurrentUserId, db: Session = Depends(get_db)
) -> list[MemberResponse]:
    document, _ = _resolve(doc_id, user_id, db)

    rows = (
        db.query(DocumentMember, User)
        .join(User, User.id == DocumentMember.user_id)
        .filter(DocumentMember.document_id == document.id)
        .order_by(User.email)
        .all()
    )
    return [MemberResponse.of(member, user) for member, user in rows]


@router.post("/{doc_id}/members", response_model=MemberResponse)
def add_member(
    doc_id: str,
    data: MemberCreate,
    user_id: CurrentUserId,
    db: Session = Depends(get_db),
) -> MemberResponse:
    document = _require_owner(doc_id, user_id, db)

    user = db.query(User).filter(User.email == data.email).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No user with that email",
        )

    if user.id == document.owner_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The owner already has full access",
        )

    member = (
        db.query(DocumentMember)
        .filter(
            DocumentMember.document_id == document.id,
            DocumentMember.user_id == user.id,
        )
        .first()
    )

    if member is None:
        member = DocumentMember(
            document_id=document.id,
            user_id=user.id,
            role=data.role,
        )
        db.add(member)
    else:
        member.role = data.role

    document.permissions_version += 1
    db.commit()
    db.refresh(member)
    return MemberResponse.of(member, user)


@router.delete(
    "/{doc_id}/members/{member_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_member(
    doc_id: str, member_user_id: UUID, user_id: CurrentUserId, db: Session = Depends(get_db)
) -> None:
    document = _require_owner(doc_id, user_id, db)

    deleted = (
        db.query(DocumentMember)
        .filter(
            DocumentMember.document_id == document.id,
            DocumentMember.user_id == member_user_id,
        )
        .delete()
    )

    if deleted:
        document.permissions_version += 1

    db.commit()


# ws handshake
@router.post("/{doc_id}/ticket", response_model=TicketResponse)
def mint_ticket(
    doc_id: str, user_id: CurrentUserId, db: Session = Depends(get_db)
) -> TicketResponse:
    _, role = _resolve(doc_id, user_id, db)

    ticket, expires_at = issue(
        user_id=str(user_id),
        doc_id=str(doc_id),
        role=role,
        secret=settings.secret_key,
        ttl_seconds=settings.ticket_ttl_seconds,
    )

    return TicketResponse(ticket=ticket, expires_at=expires_at)
