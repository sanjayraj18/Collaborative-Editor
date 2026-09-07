from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from pycrdt import Doc
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.database.database import SessionLocal
from app.database.schemas import DocumentOp, DocumentSnapshot

logger = logging.getLogger(__name__)


def _candidate_doc_ids(db) -> list[UUID]:
    return [row.doc_id for row in db.query(DocumentOp.doc_id).distinct().all()]


def _compact_one(doc_id: UUID) -> bool:
    with SessionLocal() as db:
        snapshot_row = (
            db.query(DocumentSnapshot)
            .filter(DocumentSnapshot.doc_id == doc_id)
            .order_by(DocumentSnapshot.seq.desc())
            .first()
        )
        snapshot_seq = snapshot_row.seq if snapshot_row else 0

        op_rows = (
            db.query(DocumentOp)
            .filter(DocumentOp.doc_id == doc_id, DocumentOp.seq > snapshot_seq)
            .order_by(DocumentOp.seq.asc())
            .all()
        )

        if len(op_rows) < settings.snapshot_every_n_ops:
            return False

        
        scratch = Doc()
        if snapshot_row is not None:
            scratch.apply_update(snapshot_row.state)
        for op in op_rows:
            scratch.apply_update(op.payload)

        new_seq = op_rows[-1].seq
        new_state = scratch.get_update()

        db.add(DocumentSnapshot(doc_id=doc_id, seq=new_seq, state=new_state))
        db.query(DocumentOp).filter(
            DocumentOp.doc_id == doc_id, DocumentOp.seq <= new_seq
        ).delete()
        if snapshot_row is not None:
            db.query(DocumentSnapshot).filter(
                DocumentSnapshot.doc_id == doc_id,
                DocumentSnapshot.seq < new_seq,
            ).delete()
        db.commit()

    logger.info(
        "doc_compacted doc=%s seq=%d ops_collapsed=%d", doc_id, new_seq, len(op_rows)
    )
    return True


def _run_sweep() -> int:
    with SessionLocal() as db:
        doc_ids = _candidate_doc_ids(db)

    compacted = 0
    for doc_id in doc_ids:
        if _compact_one(doc_id):
            compacted += 1
    return compacted


_task: asyncio.Task[None] | None = None


async def _sweep_loop() -> None:
    while True:
        await asyncio.sleep(settings.compaction_interval_seconds)
        try:
            compacted = await run_in_threadpool(_run_sweep)
            if compacted:
                logger.info("compaction_sweep_complete documents=%d", compacted)
        except Exception:
            logger.exception("compaction_sweep_failed")


def start() -> None:
    global _task
    if _task is None:
        _task = asyncio.create_task(_sweep_loop(), name="compaction-sweep")
        logger.info(
            "compaction_start interval=%ds threshold=%d",
            settings.compaction_interval_seconds, settings.snapshot_every_n_ops,
        )


async def stop() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    await asyncio.gather(_task, return_exceptions=True)
    _task = None