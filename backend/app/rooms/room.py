import asyncio
import logging

from pycrdt import Awareness, Doc

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

        self._ticker: asyncio.Task[None] | None = None
        self._empty_since: float | None = None

        self._permissions_version = 1

        self._seq = 0

        self._doc: Doc = Doc()

        #for delayed brodcasting
        self._batch_state_before : bytes | None = None
        self._pending_acks: list[tuple[Connection, int]] = []
        self._batch_contributors: set[Connection] = set()
        self._flush_handle: asyncio.TimerHandle | None = None

        self._awareness = Awareness(Doc())
        self._awareness_dirty = False
        self._awareness_handle: asyncio.TimerHandle | None = None


    @property
    def current_seq(self) -> int:
        return self._seq

    @property
    def member_count(self) -> int:
        return len(self._members)


    def _heartbeat(self) -> None:
        """Not async, for the same reason as _dispatch: nothing here may await."""
        for member in self._members:
            if member.is_stale():
                logger.info(
                    "member_stale doc=%s conn=%s", self.doc_id, member.conn_id
                )
                member.close(CloseCode.GOING_AWAY)
                continue
            member.ping()


    def _dispatch(self, sender : Connection, frame : Frame) -> None:
        if frame.type is FrameType.UPDATE:
            self._handle_update(sender, frame)
        elif frame.type is FrameType.SYNC_STEP1:
            self._handle_sync_step1(sender, frame)
        elif frame.type is FrameType.SYNC_STEP2:
            self._handle_sync_step2(sender, frame)
        elif frame.type is FrameType.AWARENESS:
            self._handle_awareness(sender, frame)
        else:
            logger.debug(
                "room_ignored doc=%s type=%s", self.doc_id, frame.type.name
            )


    def _handle_sync_step1(self, sender : Connection, frame : Frame) -> None:
        """Client sent its state vector — answer with what it's missing."""
        try:
            diff = self._doc.get_update(frame.payload)
        except ValueError:
            logger.warning("room_bad_state_vector doc=%s conn=%s", self.doc_id, sender.conn_id)
            sender.close(CloseCode.PROTOCOL_ERROR)
            return
        sender.send(Frame.data(FrameType.SYNC_STEP2, diff))


    def _handle_sync_step2(self, sender: Connection, frame: Frame) -> None:
        """Client sent a diff — either answering our SYNC_STEP1, or its own
        locally-stored state offered up front."""

        try:
            self._doc.apply_update(frame.payload)
        except ValueError:
            logger.warning("room_bad_sync_step2 doc=%s conn=%s", self.doc_id, sender.conn_id)
            sender.close(CloseCode.PROTOCOL_ERROR)


    def _handle_update(self , sender : Connection, frame : Frame) -> None:
        if not sender.role.can_write:
            logger.warning(
                "room_reader_wrote doc=%s conn=%s role=%s",
                self.doc_id, sender.conn_id, sender.role,
            )
            sender.close(CloseCode.UNAUTHORIZED)
            return


        if self._batch_state_before is None:
            self._batch_state_before = self._doc.get_state()
            loop = asyncio.get_running_loop()
            self._flush_handle = loop.call_later(
                settings.update_coalesce_ms / 1000, self._flush_updates
            )

        try:
            self._doc.apply_update(frame.payload)
        except ValueError:
            logger.warning("room_bad_update doc=%s conn=%s", self.doc_id, sender.conn_id)
            sender.close(CloseCode.PROTOCOL_ERROR)
            return

        self._pending_acks.append((sender, frame.seq))
        self._batch_contributors.add(sender)


    def _flush_updates(self) -> None:
        """Runs once per coalescing window. Not async — nothing here may await."""
        state_before = self._batch_state_before
        acks = self._pending_acks
        contributors = self._batch_contributors

        self._batch_state_before = None
        self._pending_acks = []
        self._batch_contributors = set()
        self._flush_handle = None

        if not acks:
            return

        merged = self._doc.get_update(state_before)
        self._seq += 1
        out = Frame.data(FrameType.UPDATE, merged, seq=self._seq)

        solo = next(iter(contributors)) if len(contributors) == 1 else None
        for member in self._members:
            if member is solo:
                continue
            member.send(out)

        for sender, client_seq in acks:
            sender.send(
                Frame.control(
                    FrameType.ACK,
                    {"client_seq": client_seq, "server_seq": self._seq},
                )
            )


    def _handle_awareness(self, sender: Connection, frame: Frame) -> None:
        """Presence only — never sequenced, never applied to the doc."""
        try:
            self._awareness.apply_awareness_update(frame.payload, origin=sender.conn_id)
        except ValueError:
            logger.warning(
                "room_bad_awareness doc=%s conn=%s", self.doc_id, sender.conn_id
            )
            sender.close(CloseCode.PROTOCOL_ERROR)
            return

        self._awareness_dirty = True
        if self._awareness_handle is None:
            loop = asyncio.get_running_loop()
            self._awareness_handle = loop.call_later(
                settings.awareness_coalesce_ms / 1000, self._flush_awareness
            )


    def _flush_awareness(self) -> None:
        self._awareness_handle = None
        if not self._awareness_dirty:
            return
        self._awareness_dirty = False

        client_ids = [
            cid for cid in self._awareness.states if cid != self._awareness.client_id
        ]
        if not client_ids:
            return

        merged = self._awareness.encode_awareness_update(client_ids)
        out = Frame.data(FrameType.AWARENESS, merged)
        for member in self._members:
            member.send(out)


    async def _tick_loop(self) -> None:
     """One timer per room, not one per connection."""
     while True:
        await asyncio.sleep(settings.ping_interval_seconds)
        self._heartbeat()


    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name=f"room:{self.doc_id}")
            self._ticker = asyncio.create_task(
                self._tick_loop(), name=f"tick:{self.doc_id}"
            )
            self._empty_since = asyncio.get_running_loop().time()
            logger.info("room_start doc=%s", self.doc_id)


    async def stop(self) -> None:
        if self._task is None:
            return

        if self._flush_handle is not None:
            self._flush_handle.cancel()
            self._flush_handle = None
        if self._awareness_handle is not None:
            self._awareness_handle.cancel()
            self._awareness_handle = None

        tasks = [t for t in (self._task, self._ticker) if t is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

        self._task = None
        self._ticker = None
        logger.info("room_stop doc=%s", self.doc_id)


    def apply_permissions_version(self, version: int) -> None:

        if version == self._permissions_version:
            return

        stale_version, self._permissions_version = self._permissions_version, version
        logger.info("permissions_changed doc=%s %d -> %d", self.doc_id, stale_version, version)

        for member in list(self._members):
            if not member.role.can_read:
                member.close(CloseCode.UNAUTHORIZED)


    async def _run(self) -> None:
        while True:
            sender, frame = await self._inbox.get()
            self._dispatch(sender, frame)


    def join(self, connection : Connection) -> None:
        self._members.add(connection)
        self._empty_since = None
        connection.send(Frame.data(FrameType.SYNC_STEP1, self._doc.get_state()))

        known = [
            cid for cid in self._awareness.states if cid != self._awareness.client_id
        ]
        if known:
            connection.send(
                Frame.data(
                    FrameType.AWARENESS, self._awareness.encode_awareness_update(known)
                )
            )

        logger.info(
            "room_join doc=%s conn=%s members=%d",
            self.doc_id, connection.conn_id, len(self._members),
        )



    def leave(self, connection : Connection) -> None:
        self._members.discard(connection)
        if not self._members:
            self._empty_since = asyncio.get_running_loop().time()
        logger.info("room_leave doc=%s conn=%s members=%d",self.doc_id, connection.conn_id, len(self._members))


    def idle_seconds(self) -> float:
        """How long this room has had no members. 0.0 while occupied."""
        if self._empty_since is None:
            return 0.0
        return asyncio.get_running_loop().time() - self._empty_since


    async def submit(self, connection: Connection, frame: Frame) -> None:
        await self._inbox.put((connection, frame))

