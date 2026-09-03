import pytest

from app.auth.roles import Role
from app.auth.passwords import hash_password
from app.database.schemas import Document, DocumentMember, User
from app.auth.authz import DocumentNotFound, authorize, get_permissions_version
from tests.conftest import requires_db

pytestmark = requires_db


def make_user(db, email):
    user = User(name="tester", email=email, password=hash_password("password123"))
    db.add(user)
    db.flush()
    return user


def make_doc(db, owner):
    doc = Document(title="Design Notes", owner_id=owner.id)
    db.add(doc)
    db.flush()
    return doc


def test_owner_is_writer(db):
    owner = make_user(db, "owner@example.com")
    doc = make_doc(db, owner)
    assert authorize(owner.id, doc.id, db) is Role.WRITER


def test_stranger_gets_none(db):
    owner = make_user(db, "owner@example.com")
    stranger = make_user(db, "stranger@example.com")
    doc = make_doc(db, owner)
    assert authorize(stranger.id, doc.id, db) is Role.NONE


@pytest.mark.parametrize("role", ["reader", "writer"])
def test_member_gets_their_role(db, role):
    owner = make_user(db, "owner@example.com")
    member = make_user(db, "member@example.com")
    doc = make_doc(db, owner)
    db.add(DocumentMember(document_id=doc.id, user_id=member.id, role=role))
    db.flush()

    assert authorize(member.id, doc.id, db) is Role(role)


def test_roles_can_read_and_write():
    assert Role.WRITER.can_write and Role.WRITER.can_read
    assert Role.READER.can_read and not Role.READER.can_write
    assert not Role.NONE.can_read and not Role.NONE.can_write


def test_missing_document_raises(db):
    user = make_user(db, "u@example.com")
    with pytest.raises(DocumentNotFound):
        authorize(user.id, "11111111-2222-3333-4444-555555555555", db)


@pytest.mark.parametrize("bad", ["", "not-a-uuid", "../../etc/passwd", None])
def test_malformed_doc_id_is_not_found(db, bad):
    user = make_user(db, "u@example.com")
    with pytest.raises(DocumentNotFound):
        authorize(user.id, bad, db)


@pytest.mark.parametrize("bad", ["", "not-a-uuid", "../../etc/passwd", None])
def test_malformed_user_id_gets_none(db, bad):
    owner = make_user(db, "owner@example.com")
    doc = make_doc(db, owner)
    assert authorize(bad, doc.id, db) is Role.NONE


def test_link_visibility_grants_writer_to_stranger(db):
    owner = make_user(db, "owner@example.com")
    stranger = make_user(db, "stranger@example.com")
    doc = make_doc(db, owner)
    doc.visibility = "link"
    db.flush()

    assert authorize(stranger.id, doc.id, db) is Role.WRITER


def test_link_visibility_does_not_demote_a_reader_member(db):
    owner = make_user(db, "owner@example.com")
    member = make_user(db, "member@example.com")
    doc = make_doc(db, owner)
    doc.visibility = "link"
    db.add(DocumentMember(document_id=doc.id, user_id=member.id, role="reader"))
    db.flush()

    assert authorize(member.id, doc.id, db) is Role.WRITER


def test_permissions_version_starts_at_one(db):
    owner = make_user(db, "owner@example.com")
    doc = make_doc(db, owner)
    assert get_permissions_version(doc.id, db) == 1