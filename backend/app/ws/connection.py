import asyncio
import logging
import uuid

from fastapi import WebSocket

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


class Connection:

    def __init__(self, websocket: WebSocket, user_id: str, doc_id: str, role: Role):
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


    async def _handshake(self) -> None:
        """Exchange CLIENT_HELLO for SERVER_HELLO. PROTOCOL.md §5 step 3."""
        raw = await asyncio.wait_for(
            self._ws.receive_bytes(),
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
        except (TimeoutError, ProtocolError) as exc:
            logger.warning("handshake_failed conn=%s detail=%s", self.conn_id, exc)
            await self._ws.close(code=CloseCode.PROTOCOL_ERROR)
            return

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
        try:
            await self._ws.close(code=int(code))
        except RuntimeError:
            pass

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
            logger.warning("send_queue_full ...")
            return

        if now - self._overflow_since >= settings.slow_consumer_grace_seconds:
            logger.warning("slow consumer evicted")
            self.close(CloseCode.SLOW_CONSUMER)

    async def _read_loop(self) -> None:
        while True:
            raw = await self._ws.receive_bytes()
            frame = decode(raw, max_frame_bytes=settings.max_frame_bytes)
            logger.info("recv conn=%s %r", self.conn_id, frame)
            self.send(frame)

    async def _write_loop(self) -> None:
        while True:
            payload = await self._queue.get()
            self._queued_bytes -= len(payload)
            await self._ws.send_bytes(payload)
