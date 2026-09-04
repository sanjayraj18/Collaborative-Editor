import asyncio
import logging

from fastapi import WebSocket
from app.protocol import Frame, decode
from app.config import settings

logger = logging.getLogger(__name__)

class Connection:

    def __init__(self,websocket : WebSocket, user_id : str, doc_id : str):
        self.user_id = user_id
        self.doc_id = doc_id
        self._ws = websocket
        self._queue : asyncio.Queue[bytes] = asyncio.Queue()
        self._reader : asyncio.Task[None] | None = None
        self._writer : asyncio.Task[None] | None = None


    def send(self, frame : Frame):
        self._queue.put_nowait(frame.encode())

    async def _read_loop(self) -> None:
        while True:
            raw = await self._ws.receive_bytes()
            frame = decode(raw, max_frame_bytes=settings.max_frame_bytes)
            logger.info("recv conn=%s %r", self.doc_id, frame)
            self.send(frame)

    async def _write_loop(self) -> None:
        while True:
            payload = await self._queue.get()
            await self._ws.send_bytes(payload)

    async def run(self):
        self._reader = asyncio.create_task(self._read_loop())
        self._writer = asyncio.create_task(self._write_loop())

        _, pending = await asyncio.wait(
            {self._reader, self._writer},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()