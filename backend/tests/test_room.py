"""Room behaviour: fan-out, sequencing, ACKs, and the registry.

Rooms are driven with a stub member rather than a real Connection. The room
only ever touches four things on a member — send, close, role, conn_id — so a
stub keeps these tests about ordering and dispatch rather than about sockets.
Connection's own behaviour is covered in test_connection.py.
"""

import asyncio
from contextlib import asynccontextmanager

from app.auth.roles import Role
from app.protocol import CloseCode, Frame, FrameType
from app.rooms.registry import RoomRegistry
from app.rooms.room import Room

DOC = "22222222-2222-2222-2222-222222222222"


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

        await room.submit(a, update(b"edit"))
        await wait_until(lambda: bool(b.received) and bool(c.received))

        assert [f.payload for f in b.received] == [b"edit"]
        assert [f.payload for f in c.received] == [b"edit"]
        # The sender gets an ACK, never a copy of what it already has.
        assert [f.type for f in a.received] == [FrameType.ACK]


async def test_leaving_stops_delivery():
    async with running_room() as room:
        a, b = FakeMember(conn_id="a"), FakeMember(conn_id="b")
        room.join(a)
        room.join(b)
        room.leave(b)

        await room.submit(a, update(b"edit"))
        await wait_until(lambda: bool(a.received))  # the ACK

        assert b.received == []
        assert room.member_count == 1


# --- sequencing -----------------------------------------------------------


async def test_sequence_is_gapless_and_ordered():
    async with running_room() as room:
        writer, watcher = FakeMember(conn_id="w"), FakeMember(conn_id="x")
        room.join(writer)
        room.join(watcher)

        for i in range(1, 51):
            await room.submit(writer, update(f"edit-{i}".encode(), client_seq=i))

        await wait_until(lambda: len(watcher.received) == 50)

        assert [f.seq for f in watcher.received] == list(range(1, 51))
        assert [f.payload for f in watcher.received] == [
            f"edit-{i}".encode() for i in range(1, 51)
        ]
        assert room.current_seq == 50


async def test_ack_maps_client_seq_to_server_seq():
    """PROTOCOL.md §4: the ACK tells a client where its edit landed."""
    async with running_room() as room:
        writer = FakeMember()
        room.join(writer)

        await room.submit(writer, update(b"one", client_seq=17))
        await room.submit(writer, update(b"two", client_seq=18))
        await wait_until(lambda: len(writer.received) == 2)

        assert [f.json() for f in writer.received] == [
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

        await room.submit(reader, update(b"not allowed"))
        await wait_until(lambda: reader.close_code is not None)

        assert reader.close_code == CloseCode.UNAUTHORIZED
        assert writer.received == []  # nothing was broadcast
        assert room.current_seq == 0  # and no sequence number was burned


# --- frame types ----------------------------------------------------------


async def test_awareness_is_relayed_but_never_sequenced():
    """Presence is not document state — it stays out of the sequence space."""
    async with running_room() as room:
        a, b = FakeMember(conn_id="a"), FakeMember(conn_id="b")
        room.join(a)
        room.join(b)

        await room.submit(a, Frame.data(FrameType.AWARENESS, b"cursor"))
        await wait_until(lambda: bool(b.received))

        assert b.received[0].type is FrameType.AWARENESS
        assert b.received[0].seq == 0
        assert room.current_seq == 0
        assert a.received == []  # no ACK for awareness


async def test_unhandled_frames_are_dropped_not_broadcast():
    """A client's PONG must not be fanned out to everyone else."""
    async with running_room() as room:
        a, b = FakeMember(conn_id="a"), FakeMember(conn_id="b")
        room.join(a)
        room.join(b)

        await room.submit(a, Frame.control(FrameType.PONG, {"t": 1}))
        await room.submit(a, update(b"after"))
        await wait_until(lambda: bool(b.received))

        assert [f.type for f in b.received] == [FrameType.UPDATE]


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


async def test_release_drops_an_empty_room():
    registry = RoomRegistry()
    room = await registry.acquire(DOC)
    member = FakeMember()
    room.join(member)
    room.leave(member)

    await registry.release(room)

    assert registry.room_count == 0
