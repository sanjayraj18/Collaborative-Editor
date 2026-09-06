#the connection was authorized once, and nothing ever re-checks
#the room owns the members, so let it periodically query the database "is everyone still allowed?" and kick out anyone who isn't.

#But you can't. This is the ironclad invariant from Phase 3: the room task must never await Postgres. Why? The room's single task processes every edit for the document one at a time. If it stopped to wait on a database query,
# every editor on that document would freeze for the duration of that query. The room must never block on I/O — it's the hot path.

import asyncio
import logging

from app.auth.authz import get_permissions_version
from app.config import settings
from app.database.database import SessionLocal
from app.rooms.registry import registry

logger = logging.getLogger(__name__)


def _read_version(doc_id : str) -> int:
    with SessionLocal() as db:
        return get_permissions_version(doc_id, db)

async def _check_loop() -> None:
    while True:
        await asyncio.sleep(settings.permission_check_seconds)

        rooms = list(registry.rooms())

        for room in rooms:
            if room.member_count == 0:
                continue
            try:
                version = await asyncio.to_thread(_read_version, room.doc_id)
            except Exception:
                logger.exception("permission_check_failed doc=%s", room.doc_id)
                continue

            room.apply_permissions_version(version)



_task: asyncio.Task[None] | None = None


def start() -> None:
    global _task
    if _task is None:
        _task = asyncio.create_task(_check_loop(), name="permission-checker")
        logger.info("permission_checker_start interval=%ds", settings.permission_check_seconds)


async def stop() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    await asyncio.gather(_task, return_exceptions=True)
    _task = None
