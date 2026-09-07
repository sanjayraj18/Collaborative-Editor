from dataclasses import dataclass
from uuid import UUID

from fastapi.concurrency import run_in_threadpool

from app.database.database import SessionLocal
from app.database.schemas import DocumentOp, DocumentSnapshot


@dataclass
class RecoveredState:
    seq: int
    snapshot: bytes | None
    ops: list[tuple[int, bytes]]  # (seq, payload), ordered, all seq > snapshot's


def _load(doc_id: UUID) -> RecoveredState:
    with SessionLocal() as db:
        snapshot_row = (
            db.query(DocumentSnapshot)
            .filter(DocumentSnapshot.doc_id == doc_id)
            .order_by(DocumentSnapshot.seq.desc())
            .first()
        )
        snapshot_seq = snapshot_row.seq if snapshot_row else 0
        snapshot_bytes = snapshot_row.state if snapshot_row else None

        op_rows = (
            db.query(DocumentOp.seq, DocumentOp.payload)
            .filter(DocumentOp.doc_id == doc_id, DocumentOp.seq > snapshot_seq)
            .order_by(DocumentOp.seq.asc())
            .all()
        )

    ops = [(row.seq, row.payload) for row in op_rows]
    last_seq = ops[-1][0] if ops else snapshot_seq
    return RecoveredState(seq=last_seq, snapshot=snapshot_bytes, ops=ops)


async def load(doc_id: UUID) -> RecoveredState:
    return await run_in_threadpool(_load, doc_id)