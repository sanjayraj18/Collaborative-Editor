import asyncio
import logging

from app.config import settings
from app.protocol import Frame
from app.ws.connection import Connection

logger = logging.getLogger(__name__)

class Room:
    def __init__(self , doc_id : str):
        self.doc_id = doc_id
        self._members : set[Connection]= set()
        self._inbox: asyncio.Queue[tuple[Connection, Frame]] = asyncio.Queue(
            maxsize=settings.room_inbox_max_frames
        )
        self._task: asyncio.Task[None] | None = None

    @property
    def member_count(self) -> int:
        return len(self._members)


    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name=f"room:{self.doc_id}")
            logger.info("room_start doc=%s", self.doc_id)


    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)

        self._task = None
        logger.info("room_stop doc=%s", self.doc_id)


    async def _run(self) -> None:
        while True:
            sender, frame = await self._inbox.get()
            self._fan_out(sender, frame)


    def join(self, connection : Connection) -> None:
        self._members.add(connection)
        logger.info("room_join doc=%s conn=%s members=%d",self.doc_id, connection.conn_id, len(self._members))


    def leave(self, connection : Connection) -> None:
        self._members.discard(connection)
        logger.info("room_leave doc=%s conn=%s members=%d",self.doc_id, connection.conn_id, len(self._members))


    async def submit(self, connection: Connection, frame: Frame) -> None:
        await self._inbox.put((connection, frame))


    def _fan_out(self, sender: Connection, frame: Frame) -> None:
        for member in self._members:
            if member is sender:
                continue
            member.send(frame)
