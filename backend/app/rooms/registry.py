import asyncio
import logging

from app.rooms.room import Room

logger = logging.getLogger(__name__)


class RoomRegistry:
    def __init__(self) -> None:
        self._rooms: dict[str, Room] = {}
        self._lock = asyncio.Lock()

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
        async with self._lock:
            if room.member_count > 0:
                return

            if self._rooms.get(room.doc_id) is not room:
                return

            del self._rooms[room.doc_id]

        await room.stop()


    async def drain_all(self) -> None:
        async with self._lock:
            rooms = list(self._rooms.values())
            self._rooms.clear()

        for room in rooms:
            await room.stop()

        logger.info("registry_drained rooms=%d", len(rooms))

registry = RoomRegistry()
