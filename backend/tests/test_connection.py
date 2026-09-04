"""Connection behaviour: handshake, framing, backpressure.

These drive Connection against a fake WebSocket rather than a real socket.
Ticket auth and the endpoint's authorization live in test_ws_auth.py; here we
only care what one connection does once it has already been accepted — so
these tests need neither a database nor a network.
"""

import asyncio

from app.auth.roles import Role
from app.config import get_settings
from app.protocol import PROTOCOL_VERSION, CloseCode, Frame, FrameType, decode
from app.ws.connection import Connection

settings = get_settings()

USER = "11111111-1111-1111-1111-111111111111"
DOC = "22222222-2222-2222-2222-222222222222"


class FakeWebSocket:
    """Enough of starlette's WebSocket for Connection to drive.

    The test pushes inbound messages; outbound payloads are collected. Setting
    `stalled` makes send_bytes block forever, which is what a client that has
    stopped reading looks like from the server once TCP buffers fill.
    """

    def __init__(self) -> None:
        self.inbox: asyncio.Queue[dict] = asyncio.Queue()
        self.sent: list[bytes] = []
        self.close_code: int | None = None
        self.stalled = False
        self._blocked = asyncio.Event()  # never set

    # --- the surface Connection uses ---

    async def receive(self) -> dict:
        return await self.inbox.get()

    async def send_bytes(self, data: bytes) -> None:
        if self.stalled:
            await self._blocked.wait()
        self.sent.append(data)

    async def close(self, code: int = 1000) -> None:
        self.close_code = code

    # --- test helpers ---

    def push(self, frame: Frame) -> None:
        self.inbox.put_nowait({"type": "websocket.receive", "bytes": frame.encode()})

    def push_bytes(self, raw: bytes) -> None:
        self.inbox.put_nowait({"type": "websocket.receive", "bytes": raw})

    def push_text(self, text: str) -> None:
        self.inbox.put_nowait({"type": "websocket.receive", "text": text})

    def push_disconnect(self, code: int = 1000) -> None:
        self.inbox.put_nowait({"type": "websocket.disconnect", "code": code})

    def frames(self) -> list[Frame]:
        return [decode(p, max_frame_bytes=settings.max_frame_bytes) for p in self.sent]


def hello(protocol: int = PROTOCOL_VERSION, client_id: int = 7) -> Frame:
    return Frame.control(
        FrameType.CLIENT_HELLO,
        {"protocol": protocol, "client_id": client_id, "last_seq": None},
    )


def make_connection(ws: FakeWebSocket, role: Role = Role.WRITER) -> Connection:
    return Connection(ws, user_id=USER, doc_id=DOC, role=role)


async def run_to_completion(ws: FakeWebSocket, role: Role = Role.WRITER) -> Connection:
    """For cases where the connection ends on its own."""
    conn = make_connection(ws, role)
    await asyncio.wait_for(conn.run(), timeout=5)
    return conn


async def wait_for_sent(ws: FakeWebSocket, count: int, within: float = 2.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + within
    while len(ws.sent) < count:
        if loop.time() > deadline:
            raise AssertionError(f"only {len(ws.sent)} frames sent, wanted {count}")
        await asyncio.sleep(0.005)


# --- handshake ------------------------------------------------------------


async def test_valid_handshake_answers_server_hello():
    ws = FakeWebSocket()
    ws.push(hello(client_id=4242))
    ws.push_disconnect()

    conn = await run_to_completion(ws)

    first = ws.frames()[0]
    assert first.type is FrameType.SERVER_HELLO

    payload = first.json()
    assert payload["conn_id"] == conn.conn_id
    assert payload["doc_id"] == DOC
    assert payload["role"] == "writer"  # not "<enum 'Role'>"
    assert payload["ping_interval_ms"] == settings.ping_interval_seconds * 1000
    assert conn.client_id == 4242


async def test_wrong_first_frame_closes_4002():
    ws = FakeWebSocket()
    ws.push(Frame.data(FrameType.UPDATE, b"too soon"))

    await run_to_completion(ws)

    assert ws.close_code == CloseCode.PROTOCOL_ERROR


async def test_protocol_mismatch_closes_4002():
    ws = FakeWebSocket()
    ws.push(hello(protocol=PROTOCOL_VERSION + 1))

    await run_to_completion(ws)

    assert ws.close_code == CloseCode.PROTOCOL_ERROR


async def test_text_frame_closes_4002():
    """PROTOCOL.md §1: binary frames only."""
    ws = FakeWebSocket()
    ws.push_text('{"protocol":1}')

    await run_to_completion(ws)

    assert ws.close_code == CloseCode.PROTOCOL_ERROR


async def test_silence_closes_after_the_hello_deadline(monkeypatch):
    monkeypatch.setattr(settings, "hello_timeout_seconds", 0.05)
    ws = FakeWebSocket()  # nothing pushed

    await run_to_completion(ws)

    assert ws.close_code == CloseCode.PROTOCOL_ERROR


async def test_oversized_frame_closes_4002():
    ws = FakeWebSocket()
    ws.push(hello())
    ws.push_bytes(b"\x12" + bytes(8) + b"x" * (settings.max_frame_bytes + 1))

    await run_to_completion(ws)

    assert ws.close_code == CloseCode.PROTOCOL_ERROR


# --- steady state ---------------------------------------------------------


async def test_update_is_echoed():
    ws = FakeWebSocket()
    ws.push(hello())
    ws.push(Frame.data(FrameType.UPDATE, b"payload"))

    conn = make_connection(ws)
    task = asyncio.create_task(conn.run())

    await wait_for_sent(ws, 2)  # SERVER_HELLO then the echo
    conn.close(CloseCode.NORMAL)
    await asyncio.wait_for(task, timeout=2)

    out = ws.frames()
    assert out[0].type is FrameType.SERVER_HELLO
    assert out[1].type is FrameType.UPDATE
    assert out[1].payload == b"payload"


async def test_duplicate_hello_closes_4002():
    ws = FakeWebSocket()
    ws.push(hello())
    ws.push(hello())

    await run_to_completion(ws)

    assert ws.close_code == CloseCode.PROTOCOL_ERROR


async def test_client_disconnect_closes_1001():
    ws = FakeWebSocket()
    ws.push(hello())
    ws.push_disconnect()

    await run_to_completion(ws)

    assert ws.close_code == CloseCode.GOING_AWAY


# --- backpressure ---------------------------------------------------------
# No writer task here, so nothing drains the queue: send() is exercised on its
# own, which is where the policy actually lives.


async def test_send_refuses_past_the_frame_bound():
    conn = make_connection(FakeWebSocket())
    frame = Frame.data(FrameType.UPDATE, b"x")

    accepted = sum(conn.send(frame) for _ in range(settings.send_queue_max_frames + 10))

    assert accepted == settings.send_queue_max_frames


async def test_send_refuses_past_the_byte_bound():
    """256 tiny frames is nothing; 256 large ones is not. Both bounds matter."""
    conn = make_connection(FakeWebSocket())
    big = Frame.data(FrameType.UPDATE, b"x" * (64 * 1024))

    accepted = sum(conn.send(big) for _ in range(settings.send_queue_max_frames))

    assert accepted < settings.send_queue_max_frames
    assert conn._queued_bytes <= settings.send_queue_max_bytes


async def test_first_refusal_only_starts_the_clock(monkeypatch):
    monkeypatch.setattr(settings, "slow_consumer_grace_seconds", 5.0)
    conn = make_connection(FakeWebSocket())
    frame = Frame.data(FrameType.UPDATE, b"x")

    while conn.send(frame):
        pass

    assert conn._overflow_since is not None
    assert conn._close_code is None  # grace has not run out yet


async def test_overflow_past_grace_evicts_with_4008(monkeypatch):
    monkeypatch.setattr(settings, "slow_consumer_grace_seconds", 0.05)
    conn = make_connection(FakeWebSocket())
    frame = Frame.data(FrameType.UPDATE, b"x")

    while conn.send(frame):
        pass

    await asyncio.sleep(0.06)
    conn.send(frame)  # a later attempt finds the grace window spent

    assert conn._close_code == CloseCode.SLOW_CONSUMER


async def test_draining_a_little_does_not_clear_the_clock():
    """Hysteresis: one free slot is not "caught up"."""
    conn = make_connection(FakeWebSocket())
    frame = Frame.data(FrameType.UPDATE, b"x")

    while conn.send(frame):
        pass
    started_at = conn._overflow_since

    payload = conn._queue.get_nowait()
    conn._queued_bytes -= len(payload)

    assert conn.send(frame)
    assert conn._overflow_since == started_at


async def test_draining_below_half_clears_the_clock():
    conn = make_connection(FakeWebSocket())
    frame = Frame.data(FrameType.UPDATE, b"x")

    while conn.send(frame):
        pass

    while conn._queue.qsize() > settings.send_queue_max_frames // 2 - 1:
        payload = conn._queue.get_nowait()
        conn._queued_bytes -= len(payload)

    assert conn.send(frame)
    assert conn._overflow_since is None


# --- the exit criterion for Phase 2 --------------------------------------


async def test_a_stalled_client_does_not_stall_a_healthy_one(monkeypatch):
    """One client that stops reading must not affect anyone else."""
    monkeypatch.setattr(settings, "slow_consumer_grace_seconds", 0.05)

    stalled_ws, healthy_ws = FakeWebSocket(), FakeWebSocket()
    stalled_ws.push(hello())
    healthy_ws.push(hello())

    stalled = make_connection(stalled_ws)
    healthy = make_connection(healthy_ws)
    stalled_task = asyncio.create_task(stalled.run())
    healthy_task = asyncio.create_task(healthy.run())

    await wait_for_sent(stalled_ws, 1)
    await wait_for_sent(healthy_ws, 1)

    stalled_ws.stalled = True  # this one stops reading

    # Fan out to both, the way a room will in Phase 3.
    frame = Frame.data(FrameType.UPDATE, b"broadcast")
    for _ in range(settings.send_queue_max_frames + 50):
        stalled.send(frame)
        healthy.send(frame)
        await asyncio.sleep(0)  # let the healthy writer drain

    await asyncio.sleep(0.06)
    stalled.send(frame)  # trips the grace window

    await asyncio.wait_for(stalled_task, timeout=2)
    assert stalled_ws.close_code == CloseCode.SLOW_CONSUMER

    # The healthy connection kept receiving throughout and is still up.
    assert len(healthy_ws.sent) > settings.send_queue_max_frames
    assert healthy._close_code is None

    healthy.close(CloseCode.NORMAL)
    await asyncio.wait_for(healthy_task, timeout=2)
    assert healthy_ws.close_code == CloseCode.NORMAL
