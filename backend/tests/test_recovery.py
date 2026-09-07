"""Phase 8's exit proof: real bytes through OpLogWriter into real Postgres,
read back by recovery.load, and reconstructed into real CRDT content by
Room.recover. Every other Phase 8 test uses fakes/monkeypatches on purpose —
this is the one file where that would defeat the point.

OpLogWriter._write_batch and recovery._load each open their own SessionLocal()
session, independent of conftest.py's `db` fixture (which wraps everything in
a transaction that is always rolled back). That means this file needs a
document row that is actually committed — invisible to `db`, visible to
everything else — and must clean up after itself instead of relying on
rollback.
"""

from uuid import uuid4

import pytest
from pycrdt import Doc, Text

from app.auth.passwords import hash_password
from app.database.database import SessionLocal
from app.database.schemas import Document, DocumentOp, DocumentSnapshot, User
from app.persistence import recovery
from app.persistence.op_log import OpLogWriter
from app.rooms.room import Room
from tests.conftest import requires_db

pytestmark = requires_db


@pytest.fixture
def real_doc_id(engine):
    """A User + Document row committed for real, cleaned up for real.

    Deleting the user cascades (at the DB level, ondelete="CASCADE" all the
    way down) through the document to its doc_ops/doc_snapshots rows, so
    that's the only cleanup this needs.
    """
    with SessionLocal() as db:
        user = User(
            name="tester",
            email=f"recovery-{uuid4()}@example.com",
            password=hash_password("password123"),
        )
        db.add(user)
        db.flush()
        doc = Document(title="Recovery Test Doc", owner_id=user.id)
        db.add(doc)
        db.commit()
        doc_id, user_id = doc.id, user.id

    yield doc_id

    with SessionLocal() as db:
        db.query(User).filter(User.id == user_id).delete()
        db.commit()


# --- op_log writes really land, recovery reads them back back --------------


async def test_write_batch_persists_real_rows_and_recovery_reads_them_back(real_doc_id):
    writer = OpLogWriter()
    fired = []
    writer.enqueue(doc_id=real_doc_id, seq=1, payload=b"payload-one", on_durable=lambda: fired.append(1))
    writer.enqueue(doc_id=real_doc_id, seq=2, payload=b"payload-two", on_durable=lambda: fired.append(2))

    await writer._flush_once()  # the real _write_batch this time — no monkeypatch

    assert fired == [1, 2]  # callbacks only fired because the commit actually succeeded

    state = await recovery.load(real_doc_id)

    assert state.seq == 2
    assert state.snapshot is None
    assert state.ops == [(1, b"payload-one"), (2, b"payload-two")]


async def test_recovery_load_for_a_document_with_no_ops(real_doc_id):
    state = await recovery.load(real_doc_id)

    assert state.seq == 0
    assert state.snapshot is None
    assert state.ops == []


async def test_recovery_load_only_returns_ops_after_the_snapshot(real_doc_id):
    """Mirrors what compaction.py leaves behind: a snapshot plus whatever
    landed after it. recovery.load must never re-hand-out ops a snapshot
    already absorbed."""
    with SessionLocal() as db:
        db.add(DocumentSnapshot(doc_id=real_doc_id, seq=5, state=b"snapshot-state"))
        db.add(DocumentOp(doc_id=real_doc_id, seq=6, payload=b"op-six"))
        db.add(DocumentOp(doc_id=real_doc_id, seq=7, payload=b"op-seven"))
        db.commit()

    state = await recovery.load(real_doc_id)

    assert state.seq == 7
    assert state.snapshot == b"snapshot-state"
    assert state.ops == [(6, b"op-six"), (7, b"op-seven")]


# --- Room.recover reconstructs real CRDT content ----------------------------


async def test_room_recover_reconstructs_real_document_content_from_persisted_ops(real_doc_id):
    """The actual guarantee Phase 8 exists for: kill the process, come back,
    and the room's content is exactly what clients had committed —
    reconstructed from real bytes that traveled through OpLogWriter into
    Postgres and back out through recovery.load, not from an in-memory stub.
    """
    seed = Doc()
    seed["content"] = Text()

    before = seed.get_state()
    with seed.transaction():
        seed["content"] += "hello"
    op_one = seed.get_update(before)

    before = seed.get_state()
    with seed.transaction():
        seed["content"] += " world"
    op_two = seed.get_update(before)

    writer = OpLogWriter()
    writer.enqueue(doc_id=real_doc_id, seq=1, payload=op_one, on_durable=lambda: None)
    writer.enqueue(doc_id=real_doc_id, seq=2, payload=op_two, on_durable=lambda: None)
    await writer._flush_once()

    state = await recovery.load(real_doc_id)

    room = Room(str(real_doc_id))
    room.recover(state.seq, state.snapshot, state.ops)

    assert room.current_seq == 2
    # .get(type=Text), not the bare subscript — a key introduced purely by
    # apply_update has no locally-cached Python wrapper yet.
    assert str(room._doc.get("content", type=Text)) == "hello world"


async def test_room_recover_applies_snapshot_before_replaying_newer_ops(real_doc_id):
    """The compaction-boundary case: content lives partly in a snapshot,
    partly in ops after it, and Room.recover must merge both into one doc."""
    seed = Doc()
    seed["content"] = Text()
    with seed.transaction():
        seed["content"] += "hello"
    snapshot_state = seed.get_update()  # everything up to and including "hello"

    before = seed.get_state()
    with seed.transaction():
        seed["content"] += " world"
    op_after_snapshot = seed.get_update(before)

    with SessionLocal() as db:
        db.add(DocumentSnapshot(doc_id=real_doc_id, seq=1, state=snapshot_state))
        db.add(DocumentOp(doc_id=real_doc_id, seq=2, payload=op_after_snapshot))
        db.commit()

    state = await recovery.load(real_doc_id)
    assert state.seq == 2

    room = Room(str(real_doc_id))
    room.recover(state.seq, state.snapshot, state.ops)

    assert room.current_seq == 2
    assert str(room._doc.get("content", type=Text)) == "hello world"
