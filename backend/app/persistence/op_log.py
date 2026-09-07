from dataclasses import dataclass
import logging
import asyncio
from typing import Callable
from uuid import UUID

from sqlalchemy import insert
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.database.database import SessionLocal
from app.database.schemas import DocumentOp

logger = logging.getLogger(__name__)


@dataclass
class _PendingOp:
    doc_id: UUID
    seq: int
    payload: bytes
    on_durable: Callable[[], None]


class OpLogWriter:
    def __init__(self) -> None:
        self._pending : list[_PendingOp] = []
        self._task : asyncio.Task[None] | None = None

        
    def enqueue(self, doc_id :UUID , seq : int, payload : bytes , on_durable : Callable[[],None]):
        self._pending.append(_PendingOp(doc_id, seq, payload, on_durable))


    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(settings.op_log_batch_ms / 1000)
            await self._flush_once()


    async def _flush_once(self) -> None:
        if not self._pending:
            return

        batch = self._pending
        self._pending = []

        try:
            await run_in_threadpool(self._write_batch, batch)
        except Exception:
            logger.exception("op_log_write_failed batch_size=%d", len(batch))
            return

        for op in batch:
            op.on_durable()


    def _write_batch(self, batch: list[_PendingOp]) -> None:
        
        with SessionLocal() as db:
            db.execute(
                insert(DocumentOp),
                [
                    {"doc_id": op.doc_id, "seq": op.seq, "payload": op.payload}
                    for op in batch
                ],
            )
            db.commit()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._flush_loop(), name="op-log-writer")
            logger.info("op_log_writer_start batch_ms=%d", settings.op_log_batch_ms)


    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        await self._flush_once()


op_log = OpLogWriter()

