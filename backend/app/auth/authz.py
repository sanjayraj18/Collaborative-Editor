from app.auth.roles import Role
from uuid import UUID
from sqlalchemy.orm import Session

from app.database.schemas import Document, DocumentMember

def _as_uuid(value: str | UUID) -> UUID | None:

    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return None
   

def authorize(user_id: str | UUID, doc_id: str | UUID, db: Session) -> Role:

    user_uuid = _as_uuid(user_id)
    doc_uuid = _as_uuid(doc_id)

    if user_uuid is None or doc_uuid is None:
        return Role.NONE

    document = db.query(Document).filter(Document.id == doc_uuid).first()
    if document is None:
        return Role.NONE

    if document.owner_id == user_uuid:
        return Role.WRITER

    member = (db.query(DocumentMember).filter(DocumentMember.document_id == doc_uuid,DocumentMember.user_id == user_uuid,).first())
    if member is None:
        return Role.NONE

    try:
        return Role(member.role)
    except (ValueError, TypeError):
        return Role.NONE
