import asyncio
import logging

from app.config import settings
from app.protocol import CloseCode, Frame, FrameType
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

        self._seq = 0

    @property
    def current_seq(self) -> int:
        return self._seq

    @property
    def member_count(self) -> int:
        return len(self._members)


    def ticker(self):
        pass


    def _dispatch(self, sender : Connection, frame : Frame) -> None:
        if frame.type is FrameType.UPDATE:
            self._handle_update(sender, frame)
        elif frame.type is FrameType.AWARENESS:
            self._relay(sender, frame)
        else:
            logger.debug(
                "room_ignored doc=%s type=%s", self.doc_id, frame.type.name
            )


    def _handle_update(self , sender : Connection, frame : Frame) -> None:
        if not sender.role.can_write:
            logger.warning(
                "room_reader_wrote doc=%s conn=%s role=%s",
                self.doc_id, sender.conn_id, sender.role,
            )
            sender.close(CloseCode.UNAUTHORIZED)
            return
        self._seq += 1

        out = Frame.data(FrameType.UPDATE, frame.payload, seq=self._seq)
        self._relay(sender, out)

        sender.send(
            Frame.control(
                FrameType.ACK,
                {"client_seq": frame.seq, "server_seq": self._seq},
            )
        )


    def _relay(self, sender: Connection, frame: Frame) -> None:
        for member in self._members:
            if member is sender:
                continue
            member.send(frame)


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
            self._dispatch(sender, frame)


    def join(self, connection : Connection) -> None:
        self._members.add(connection)
        logger.info("room_join doc=%s conn=%s members=%d",self.doc_id, connection.conn_id, len(self._members))


    def leave(self, connection : Connection) -> None:
        self._members.discard(connection)
        logger.info("room_leave doc=%s conn=%s members=%d",self.doc_id, connection.conn_id, len(self._members))


    async def submit(self, connection: Connection, frame: Frame) -> None:
        await self._inbox.put((connection, frame))

