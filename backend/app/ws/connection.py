import asyncio
import contextlib
import logging
import uuid
from collections.abc import Awaitable, Callable

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from app.auth.roles import Role
from app.config import settings
from app.protocol import (
    PROTOCOL_VERSION,
    CloseCode,
    Frame,
    FrameType,
    ProtocolError,
    decode,
)

logger = logging.getLogger(__name__)

FrameHandler = Callable[["Connection", Frame], Awaitable[None]]


async def _drop(connection: "Connection", frame: Frame) -> None:
    return None


class Connection:

    def __init__(self, websocket: WebSocket, user_id: str, doc_id: str, role: Role, on_frame: FrameHandler = _drop):
        self.conn_id = uuid.uuid4().hex[:16]
        self.user_id = user_id
        self.doc_id = doc_id
        self.role = role

        self.client_id: int = 0
        self.last_seq: int | None = None

        self._ws = websocket
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=settings.send_queue_max_frames)
        self._queued_bytes = 0
        self._overflow_since: float | None = None

        self._reader: asyncio.Task[None] | None = None
        self._writer: asyncio.Task[None] | None = None

        self._close_code: CloseCode | None = None
        self._closing = asyncio.Event()

        #this is to link the connection to the rooms or sending the client frame to the room
        self._on_frame = on_frame


    async def _receive_raw(self) -> bytes:
        message = await self._ws.receive()
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(message.get("code", 1005))
        raw: bytes | None = message.get("bytes")
        if raw is None:
            raise ProtocolError("expected a binary frame, got text")
        return raw


    async def _handshake(self) -> None:
        """Exchange CLIENT_HELLO for SERVER_HELLO. PROTOCOL.md §5 step 3."""
        raw = await asyncio.wait_for(
            self._receive_raw(),
            timeout=settings.hello_timeout_seconds,
        )
        frame = decode(raw, max_frame_bytes=settings.max_frame_bytes)

        if frame.type is not FrameType.CLIENT_HELLO:
            raise ProtocolError(
                f"first frame was {frame.type.name}, expected CLIENT_HELLO"
            )

        data = frame.json()

        if data.get("protocol") != PROTOCOL_VERSION:
            raise ProtocolError(f"protocol mismatch: {data.get('protocol')!r}")

        self.client_id = data.get("client_id", 0)
        self.last_seq = data.get("last_seq")

        # Sent directly, not through the queue — the writer task does not exist
        # yet, so there is no second sender to race with. This is the only place
        # in the class allowed to touch send_bytes outside _write_loop.
        await self._ws.send_bytes(
            Frame.control(
                FrameType.SERVER_HELLO,
                {
                    "conn_id": self.conn_id,
                    "doc_id": self.doc_id,
                    "role": str(self.role),
                    "server_seq": 0,     # Phase 3: the room's current sequence
                    "resumed": False,    # Phase 6: true when replaying
                    "ping_interval_ms": settings.ping_interval_seconds * 1000,
                },
            ).encode()
        )


    async def run(self) -> None:
        try:
            await self._handshake()
        except TimeoutError:
            logger.warning("hello_timeout conn=%s", self.conn_id)
            await self._ws.close(code=CloseCode.PROTOCOL_ERROR)
            return
        except ProtocolError as exc:
            logger.warning(
                "handshake_failed conn=%s detail=%s", self.conn_id, exc.message
            )
            await self._ws.close(code=exc.close_code)
            return
        except WebSocketDisconnect:
            return  # client hung up mid-handshake; nothing to close

        logger.info(
            "conn_open conn=%s doc=%s role=%s client_id=%s",
            self.conn_id, self.doc_id, self.role, self.client_id,
        )

        self._reader = asyncio.create_task(self._read_loop())
        self._writer = asyncio.create_task(self._write_loop())
        closer = asyncio.create_task(self._closing.wait())

        _, pending = await asyncio.wait(
            {self._reader, self._writer, closer},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()

        await asyncio.gather(*pending, return_exceptions=True)

        code = self._close_code or CloseCode.NORMAL
        logger.info("conn_close conn=%s code=%d", self.conn_id, int(code))
        with contextlib.suppress(RuntimeError):  # peer already closed it
            await self._ws.close(code=int(code))

    def send(self, frame: Frame) -> bool:
        if self._closing.is_set():
            return False

        payload = frame.encode()
        over_frames = self._queue.full()
        over_bytes = self._queued_bytes + len(payload) > settings.send_queue_max_bytes

        if over_frames or over_bytes:
            self._note_overflow()
            return False

        self._queue.put_nowait(payload)
        self._queued_bytes += len(payload)

        if self._queue.qsize() * 2 <= settings.send_queue_max_frames:
            self._overflow_since = None

        return True


    def close(self, code: CloseCode) -> None:
        if self._close_code is None:
            self._close_code = code
        self._closing.set()

    def _note_overflow(self) -> None:
        now = asyncio.get_running_loop().time()

        if self._overflow_since is None:
            self._overflow_since = now
            logger.warning(
                "send_queue_full conn=%s frames=%d bytes=%d",
                self.conn_id, self._queue.qsize(), self._queued_bytes,
            )
            return

        if now - self._overflow_since >= settings.slow_consumer_grace_seconds:
            logger.warning(
                "slow_consumer_evicted conn=%s stalled_for=%.1fs",
                self.conn_id, now - self._overflow_since,
            )
            self.close(CloseCode.SLOW_CONSUMER)

    async def _read_loop(self) -> None:
        """Never raises. Every failure becomes a close code."""
        try:
            while True:
                raw = await self._receive_raw()
                frame = decode(raw, max_frame_bytes=settings.max_frame_bytes)

                if frame.type is FrameType.CLIENT_HELLO:
                    raise ProtocolError("duplicate CLIENT_HELLO")

                logger.info("recv conn=%s %r", self.conn_id, frame)
                await self._on_frame(self, frame)

        except WebSocketDisconnect:
            self.close(CloseCode.GOING_AWAY)
        except ProtocolError as exc:
            logger.warning(
                "protocol_error conn=%s detail=%s", self.conn_id, exc.message
            )
            self.close(exc.close_code)
        # CancelledError is a BaseException in 3.8+, so this does not swallow
        # cancellation — run() can still tear the task down cleanly.
        except Exception:
            logger.exception("reader_crashed conn=%s", self.conn_id)
            self.close(CloseCode.PROTOCOL_ERROR)

    async def _write_loop(self) -> None:
        """The sole owner of the socket's send side."""
        try:
            while True:
                payload = await self._queue.get()
                self._queued_bytes -= len(payload)
                await self._ws.send_bytes(payload)

        except (WebSocketDisconnect, RuntimeError):
            self.close(CloseCode.GOING_AWAY)
        except Exception:
            logger.exception("writer_crashed conn=%s", self.conn_id)
            self.close(CloseCode.GOING_AWAY)
