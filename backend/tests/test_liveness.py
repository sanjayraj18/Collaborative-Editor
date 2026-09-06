"""Liveness: connection staleness, the room's heartbeat, and live
re-authorization.

Reaper / idle-room collection is already covered in test_room.py. This file
covers the other three Phase 4 mechanisms: a connection noticing it has gone
quiet, the room's ticker acting on that, and a room reacting to a changed
permissions_version. Room heartbeat tests drive a real Connection over a
FakeWebSocket rather than a stub, since the property under test — a socket
actually closing — lives in Connection, not in the room.
"""

import asyncio

from app.auth.roles import Role
from app.config import get_settings
from app.protocol import CloseCode, Frame, FrameType
from app.rooms.room import Room
from app.ws.connection import Connection
from tests.test_connection import FakeWebSocket, hello, make_connection, wait_for_sent
from tests.test_room import make_update

settings = get_settings()


class RoleStub:
    """The one thing apply_permissions_version touches on a member.

    Needs send() now too: Room.join() sends a SYNC_STEP1 to every joiner,
    real Connection or not.
    """

    def __init__(self, role: Role) -> None:
        self.role = role
        self.conn_id = "stub"
        self.close_code: CloseCode | None = None

    def send(self, frame: Frame) -> bool:
        return True

    def close(self, code: CloseCode) -> None:
        if self.close_code is None:
            self.close_code = code


# --- Connection: ping / staleness -----------------------------------------


async def test_ping_sends_a_ping_frame_carrying_a_timestamp():
    """ping() only enqueues; nothing reaches the wire without the writer task
    that run() starts, so this drives a full connection rather than calling
    ping() in isolation."""
    ws = FakeWebSocket()
    ws.push(hello())
    conn = make_connection(ws)
    task = asyncio.create_task(conn.run())

    await wait_for_sent(ws, 1)  # SERVER_HELLO
    conn.ping()
    await wait_for_sent(ws, 2)

    frame = ws.frames()[1]
    assert frame.type is FrameType.PING
    assert isinstance(frame.json()["t"], int)

    conn.close(CloseCode.NORMAL)
    await asyncio.wait_for(task, timeout=2)


async def test_fresh_connection_is_not_stale():
    ws = FakeWebSocket()
    ws.push(hello())
    conn = make_connection(ws)
    task = asyncio.create_task(conn.run())

    await wait_for_sent(ws, 1)  # SERVER_HELLO
    assert conn.is_stale() is False

    conn.close(CloseCode.NORMAL)
    await asyncio.wait_for(task, timeout=2)


async def test_silence_past_the_pong_deadline_is_stale(monkeypatch):
    monkeypatch.setattr(settings, "pong_timeout_seconds", 0.05)
    ws = FakeWebSocket()
    ws.push(hello())
    conn = make_connection(ws)
    task = asyncio.create_task(conn.run())

    await wait_for_sent(ws, 1)
    await asyncio.sleep(0.08)

    assert conn.is_stale() is True

    conn.close(CloseCode.NORMAL)
    await asyncio.wait_for(task, timeout=2)


async def test_any_inbound_frame_clears_staleness(monkeypatch):
    """Not just PONG — a client mid-edit is obviously alive too."""
    monkeypatch.setattr(settings, "pong_timeout_seconds", 0.05)
    ws = FakeWebSocket()
    ws.push(hello())
    conn = make_connection(ws)
    task = asyncio.create_task(conn.run())

    await wait_for_sent(ws, 1)
    await asyncio.sleep(0.08)
    assert conn.is_stale() is True

    ws.push(Frame.data(FrameType.UPDATE, b"still here"))
    await asyncio.sleep(0.02)  # let the reader loop pick it up

    assert conn.is_stale() is False

    conn.close(CloseCode.NORMAL)
    await asyncio.wait_for(task, timeout=2)


# --- Room heartbeat: real Connection, real Room ----------------------------


async def test_heartbeat_pings_a_live_member(monkeypatch):
    monkeypatch.setattr(settings, "ping_interval_seconds", 0.02)
    ws = FakeWebSocket()
    ws.push(hello())

    room = Room("doc-heartbeat-live")
    room.start()
    conn = Connection(ws, user_id="u", doc_id=room.doc_id, role=Role.WRITER, on_frame=room.submit)
    room.join(conn)
    task = asyncio.create_task(conn.run())

    await wait_for_sent(ws, 1)  # SERVER_HELLO
    # index 1 is SYNC_STEP1 from room.join(); the heartbeat's PING is next.
    await wait_for_sent(ws, 3, within=1.0)

    assert ws.frames()[2].type is FrameType.PING

    conn.close(CloseCode.NORMAL)
    await asyncio.wait_for(task, timeout=2)
    await room.stop()


async def test_heartbeat_evicts_a_connection_that_stopped_answering(monkeypatch):
    """Phase 4's exit criterion: a client that goes quiet is reaped without
    anyone reaching into the room from outside — the ticker does it alone."""
    monkeypatch.setattr(settings, "ping_interval_seconds", 0.02)
    monkeypatch.setattr(settings, "pong_timeout_seconds", 0.05)

    ws = FakeWebSocket()
    ws.push(hello())

    room = Room("doc-heartbeat-stale")
    room.start()
    conn = Connection(ws, user_id="u", doc_id=room.doc_id, role=Role.WRITER, on_frame=room.submit)
    room.join(conn)
    task = asyncio.create_task(conn.run())

    await wait_for_sent(ws, 1)  # SERVER_HELLO, then the client goes silent

    await asyncio.wait_for(task, timeout=2)  # run() exits once close() fires

    assert ws.close_code == CloseCode.GOING_AWAY
    await room.stop()


async def test_a_talkative_member_is_never_evicted(monkeypatch):
    """The counterpart to the eviction test: activity must suppress it."""
    monkeypatch.setattr(settings, "ping_interval_seconds", 0.02)
    monkeypatch.setattr(settings, "pong_timeout_seconds", 0.06)

    ws = FakeWebSocket()
    ws.push(hello())

    room = Room("doc-heartbeat-active")
    room.start()
    conn = Connection(ws, user_id="u", doc_id=room.doc_id, role=Role.WRITER, on_frame=room.submit)
    room.join(conn)
    task = asyncio.create_task(conn.run())

    await wait_for_sent(ws, 1)

    for i in range(5):
        await asyncio.sleep(0.03)  # less than the pong deadline, each time
        ws.push(Frame.data(FrameType.UPDATE, make_update(f"keep typing {i}")))

    await asyncio.sleep(0.03)
    assert task.done() is False  # still up after 0.15s against a 0.06s deadline

    conn.close(CloseCode.NORMAL)
    await asyncio.wait_for(task, timeout=2)
    await room.stop()


# --- live permission re-check ----------------------------------------------


async def test_apply_permissions_version_is_a_noop_when_unchanged():
    room = Room("doc-perm-noop")
    member = RoleStub(Role.WRITER)
    room.join(member)

    room.apply_permissions_version(1)  # matches Room's default at construction

    assert member.close_code is None


async def test_apply_permissions_version_closes_a_member_who_can_no_longer_read():
    room = Room("doc-perm-revoke")
    revoked = RoleStub(Role.NONE)
    still_ok = RoleStub(Role.READER)
    room.join(revoked)
    room.join(still_ok)

    room.apply_permissions_version(2)

    assert revoked.close_code == CloseCode.UNAUTHORIZED
    assert still_ok.close_code is None


async def test_apply_permissions_version_only_acts_on_an_actual_change(caplog):
    room = Room("doc-perm-idempotent")
    member = RoleStub(Role.WRITER)
    room.join(member)

    with caplog.at_level("INFO", logger="app.rooms.room"):
        room.apply_permissions_version(1)  # same as the default -> no-op
        assert "permissions_changed" not in caplog.text

        room.apply_permissions_version(7)  # a real change
        assert "permissions_changed" in caplog.text
        caplog.clear()

        room.apply_permissions_version(7)  # unchanged again -> no-op
        assert "permissions_changed" not in caplog.text
