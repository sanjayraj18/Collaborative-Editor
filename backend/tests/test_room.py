"""Room behaviour: fan-out, sequencing, ACKs, and the registry.

Rooms are driven with a stub member rather than a real Connection. The room
only ever touches four things on a member — send, close, role, conn_id — so a
stub keeps these tests about ordering and dispatch rather than about sockets.
Connection's own behaviour is covered in test_connection.py.
"""

import asyncio
from contextlib import asynccontextmanager

from pycrdt import Doc, Text

from app.auth.roles import Role
from app.config import settings
from app.protocol import CloseCode, Frame, FrameType
from app.rooms.registry import RoomRegistry
from app.rooms.room import Room

DOC = "22222222-2222-2222-2222-222222222222"


def make_update(text: str = "edit") -> bytes:
    """A self-contained, valid Yjs update representing one text insert.

    Each call uses an independent Doc, so distinct calls yield distinct but
    still-mergeable updates — exactly what a real client emits per keystroke.
    Room._handle_update now calls pycrdt's apply_update on every payload, so
    arbitrary bytes (the old b"edit") are rejected with a ValueError and the
    sender closed 4002.
    """
    doc = Doc()
    doc["content"] = Text()
    with doc.transaction():
        doc["content"] += text
    return doc.get_update()


class FakeMember:
    """The slice of Connection that Room actually uses."""

    def __init__(self, role: Role = Role.WRITER, conn_id: str = "conn") -> None:
        self.role = role
        self.conn_id = conn_id
        self.received: list[Frame] = []
        self.close_code: CloseCode | None = None

    def send(self, frame: Frame) -> bool:
        self.received.append(frame)
        return True

    def close(self, code: CloseCode) -> None:
        if self.close_code is None:
            self.close_code = code


def non_sync(member: FakeMember) -> list[Frame]:
    """Everything a member received except the SYNC_STEP1 every join() sends.

    Phase 5: joining now triggers a sync handshake, so every member's very
    first received frame is SYNC_STEP1 regardless of what the test does next.
    """
    return [f for f in member.received if f.type is not FrameType.SYNC_STEP1]


def update(payload: bytes, client_seq: int = 1) -> Frame:
    return Frame.data(FrameType.UPDATE, payload, seq=client_seq)


@asynccontextmanager
async def running_room(doc_id: str = DOC):
    room = Room(doc_id)
    room.start()
    try:
        yield room
    finally:
        await room.stop()


async def wait_until(predicate, within: float = 2.0) -> None:
    """The room task runs concurrently, so assert on effects, not on timing."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + within
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition was never met")
        await asyncio.sleep(0.002)


# --- fan-out --------------------------------------------------------------


async def test_update_reaches_every_member_but_the_sender():
    async with running_room() as room:
        a, b, c = (FakeMember(conn_id=x) for x in "abc")
        for member in (a, b, c):
            room.join(member)

        payload = make_update()
        await room.submit(a, update(payload))
        await wait_until(lambda: non_sync(b) and non_sync(c))

        assert [f.payload for f in non_sync(b)] == [payload]
        assert [f.payload for f in non_sync(c)] == [payload]
        # The sender gets an ACK, never a copy of what it already has.
        assert [f.type for f in non_sync(a)] == [FrameType.ACK]


async def test_leaving_stops_delivery():
    async with running_room() as room:
        a, b = FakeMember(conn_id="a"), FakeMember(conn_id="b")
        room.join(a)
        room.join(b)
        room.leave(b)

        await room.submit(a, update(make_update()))
        await wait_until(lambda: non_sync(a))  # the ACK

        assert non_sync(b) == []
        assert room.member_count == 1


# --- sequencing -----------------------------------------------------------


async def test_sequence_is_gapless_and_ordered():
    async with running_room() as room:
        writer, watcher = FakeMember(conn_id="w"), FakeMember(conn_id="x")
        room.join(writer)
        room.join(watcher)

        payloads = [make_update(f"edit-{i}") for i in range(1, 51)]
        for i, payload in enumerate(payloads, start=1):
            await room.submit(writer, update(payload, client_seq=i))

        await wait_until(lambda: len(non_sync(watcher)) == 50)

        received = non_sync(watcher)
        assert [f.seq for f in received] == list(range(1, 51))
        assert [f.payload for f in received] == payloads
        assert room.current_seq == 50


async def test_ack_maps_client_seq_to_server_seq():
    """PROTOCOL.md §4: the ACK tells a client where its edit landed."""
    async with running_room() as room:
        writer = FakeMember()
        room.join(writer)

        await room.submit(writer, update(make_update("one"), client_seq=17))
        await room.submit(writer, update(make_update("two"), client_seq=18))
        await wait_until(lambda: len(non_sync(writer)) == 2)

        assert [f.json() for f in non_sync(writer)] == [
            {"client_seq": 17, "server_seq": 1},
            {"client_seq": 18, "server_seq": 2},
        ]


# --- authorization --------------------------------------------------------


async def test_reader_sending_an_update_is_closed_4003():
    async with running_room() as room:
        reader = FakeMember(role=Role.READER, conn_id="r")
        writer = FakeMember(conn_id="w")
        room.join(reader)
        room.join(writer)

        # Content never reaches apply_update — the role check runs first —
        # so arbitrary bytes are fine here, unlike everywhere else in this file.
        await room.submit(reader, update(b"not allowed"))
        await wait_until(lambda: reader.close_code is not None)

        assert reader.close_code == CloseCode.UNAUTHORIZED
        assert non_sync(writer) == []  # nothing was broadcast
        assert room.current_seq == 0  # and no sequence number was burned


# --- frame types ----------------------------------------------------------


async def test_awareness_is_relayed_but_never_sequenced():
    """Presence is not document state — it stays out of the sequence space."""
    async with running_room() as room:
        a, b = FakeMember(conn_id="a"), FakeMember(conn_id="b")
        room.join(a)
        room.join(b)

        await room.submit(a, Frame.data(FrameType.AWARENESS, b"cursor"))
        await wait_until(lambda: non_sync(b))

        received = non_sync(b)
        assert received[0].type is FrameType.AWARENESS
        assert received[0].seq == 0
        assert room.current_seq == 0
        assert non_sync(a) == []  # no ACK for awareness


async def test_unhandled_frames_are_dropped_not_broadcast():
    """A client's PONG must not be fanned out to everyone else."""
    async with running_room() as room:
        a, b = FakeMember(conn_id="a"), FakeMember(conn_id="b")
        room.join(a)
        room.join(b)

        await room.submit(a, Frame.control(FrameType.PONG, {"t": 1}))
        await room.submit(a, update(make_update("after")))
        await wait_until(lambda: non_sync(b))

        assert [f.type for f in non_sync(b)] == [FrameType.UPDATE]


# --- registry -------------------------------------------------------------


async def test_registry_returns_one_room_per_document():
    registry = RoomRegistry()
    first = await registry.acquire(DOC)
    second = await registry.acquire(DOC)

    assert first is second
    assert registry.room_count == 1

    await registry.drain_all()


async def test_registry_isolates_documents():
    registry = RoomRegistry()
    a = await registry.acquire("doc-a")
    b = await registry.acquire("doc-b")

    assert a is not b
    assert registry.room_count == 2

    await registry.drain_all()
    assert registry.room_count == 0


async def test_release_keeps_a_room_that_still_has_members():
    registry = RoomRegistry()
    room = await registry.acquire(DOC)
    room.join(FakeMember())

    await registry.release(room)

    assert registry.room_count == 1
    await registry.drain_all()


async def test_release_no_longer_drops_an_empty_room():
    """Phase 4: eager release would rebuild the room on every tab refresh —
    wasteful, and in Phase 8 it means re-reading a Postgres snapshot for
    nothing. Only the reaper collects idle rooms now."""
    registry = RoomRegistry()
    room = await registry.acquire(DOC)
    member = FakeMember()
    room.join(member)
    room.leave(member)

    await registry.release(room)

    assert registry.room_count == 1
    await registry.drain_all()


async def test_reaper_collects_a_room_only_after_its_ttl(monkeypatch):
    monkeypatch.setattr(settings, "reaper_interval_seconds", 0.02)
    monkeypatch.setattr(settings, "room_idle_ttl_seconds", 0.05)

    registry = RoomRegistry()
    room = await registry.acquire(DOC)
    member = FakeMember()
    room.join(member)
    room.leave(member)  # idle clock starts now

    registry.start_reaper()
    try:
        await wait_until(lambda: registry.room_count == 0, within=1.0)
    finally:
        await registry.stop_reaper()


async def test_reaper_spares_a_room_that_is_still_occupied(monkeypatch):
    monkeypatch.setattr(settings, "reaper_interval_seconds", 0.02)
    monkeypatch.setattr(settings, "room_idle_ttl_seconds", 0.05)

    registry = RoomRegistry()
    room = await registry.acquire(DOC)
    room.join(FakeMember())  # never leaves

    registry.start_reaper()
    try:
        await asyncio.sleep(0.15)  # several sweeps, well past the TTL
        assert registry.room_count == 1
    finally:
        await registry.stop_reaper()
        await registry.drain_all()
