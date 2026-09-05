import asyncio
import logging

from app.config import settings
from app.rooms.room import Room

logger = logging.getLogger(__name__)


class RoomRegistry:
    def __init__(self) -> None:
        self._rooms: dict[str, Room] = {}
        self._lock = asyncio.Lock()
        self._reaper: asyncio.Task[None] | None = None


    @property
    def room_count(self) -> int:
        return len(self._rooms)


    async def acquire(self, doc_id :str) -> Room:
        async with self._lock:
            room = self._rooms.get(doc_id)

            if room is None:
                room = Room(doc_id)
                room.start()
                self._rooms[doc_id] = room

            return room


    async def release(self, room: Room) -> None:
        return

    def rooms(self) -> list[Room]:
        return list(self._rooms.values())

    async def _reap_idle(self) -> None:
        while True:
            await asyncio.sleep(settings.reaper_interval_seconds)

            async with self._lock:
                idle = [
                    (doc_id, room)
                    for doc_id, room in self._rooms.items()
                    if room.member_count == 0
                    and room.idle_seconds() >= settings.room_idle_ttl_seconds
                ]
                for doc_id, _ in idle:
                    del self._rooms[doc_id]

            for _, room in idle:
                await room.stop()
                logger.info(
                    "room_reaped doc=%s idle_for=%.0fs",
                    room.doc_id, settings.room_idle_ttl_seconds,
                )


    def start_reaper(self) -> None:
        if self._reaper is None:
            self._reaper = asyncio.create_task(self._reap_idle(), name="room-reaper")
            logger.info(
                "reaper_start interval=%ds ttl=%ds",
                settings.reaper_interval_seconds, settings.room_idle_ttl_seconds,
            )


    async def stop_reaper(self) -> None:
        if self._reaper is None:
            return
        self._reaper.cancel()
        await asyncio.gather(self._reaper, return_exceptions=True)
        self._reaper = None


    async def drain_all(self) -> None:
        """Shutdown. Phase 9 will send 4009 to members before stopping."""
        await self.stop_reaper()

        async with self._lock:
            rooms = list(self._rooms.values())
            self._rooms.clear()

        for room in rooms:
            await room.stop()

        logger.info("registry_drained rooms=%d", len(rooms))

registry = RoomRegistry()
