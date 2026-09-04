from uuid import UUID

from sqlalchemy.orm import Session

from app.auth.roles import Role, Visibility
from app.database.schemas import Document, DocumentMember


class DocumentNotFound(Exception):
    """The document does not exist, or its id is not a well-formed UUID.

    Distinct from Role.NONE, which means "this document exists and you may not
    touch it". PROTOCOL.md declares close code 4004 for the former and 4003 for
    the latter; without this exception nothing can ever emit 4004.
    """


def _as_uuid(value: str | UUID) -> UUID | None:

    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return None


def _load(doc_id: str | UUID, db: Session) -> Document:
    doc_uuid = _as_uuid(doc_id)
    if doc_uuid is None:
        raise DocumentNotFound(str(doc_id))

    document = db.query(Document).filter(Document.id == doc_uuid).first()
    if document is None:
        raise DocumentNotFound(str(doc_id))

    return document


def role_for(document: Document, user_id: str | UUID, member_role: str | None) -> Role:

    user_uuid = _as_uuid(user_id)
    if user_uuid is None:
        return Role.NONE

    if document.owner_id == user_uuid:
        return Role.WRITER

    if document.visibility == Visibility.LINK:
        return Role.WRITER

    if member_role is None:
        return Role.NONE

    try:
        return Role(member_role)
    except (ValueError, TypeError):
        return Role.NONE


def authorize(user_id: str | UUID, doc_id: str | UUID, db: Session) -> Role:

    document = _load(doc_id, db)

    role = role_for(document, user_id, member_role=None)
    if role is not Role.NONE:
        return role

    user_uuid = _as_uuid(user_id)
    if user_uuid is None:
        return Role.NONE

    if document.owner_id == user_uuid:
        return Role.WRITER

    if document.visibility == Visibility.LINK:
        return Role.WRITER

    member = (
        db.query(DocumentMember)
        .filter(
            DocumentMember.document_id == document.id,
            DocumentMember.user_id == user_uuid,
        )
        .first()
    )
    if member is None:
        return Role.NONE

    try:
        return Role(member.role)
    except (ValueError, TypeError):
        return Role.NONE


def get_permissions_version(doc_id: str | UUID, db: Session) -> int:

    return int(_load(doc_id, db).permissions_version)
