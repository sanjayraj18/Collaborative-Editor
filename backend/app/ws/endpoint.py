from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket
from app.config import get_settings
from app.auth.roles import Role
from app.database.database import SessionLocal
from app.auth.authz import authorize
from app.protocol import CloseCode
from app.auth.origin import is_allowed
from app.auth.tickets import verify, TicketError
from app.auth.nonce import nonce_store
from starlette.concurrency import run_in_threadpool


router = APIRouter()
logger = logging.getLogger(__name__)
settings = get_settings()


def _lookup_role(user_id : str, doc_id : str) -> Role:
    with SessionLocal() as db:
        return authorize(user_id, doc_id, db)


async def _reject(websocket : WebSocket, code : CloseCode, stage : str, detail : str) -> None:
    logger.warning("ws_reject stage=%s detail=%s", stage, detail)
    await websocket.close(code=code)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin")
    doc_id = websocket.query_params.get("doc")
    raw_ticket = websocket.query_params.get("ticket")

    if not is_allowed(origin, settings.allowed_origins):
        logger.warning("ws_reject stage=origin origin=%r", origin)
        await websocket.close()
        return

    await websocket.accept()

    try:
        claims = verify(raw_ticket, secret=settings.secret_key)
    except TicketError as exc:
        await _reject(websocket, CloseCode.TICKET_INVALID, "ticket", exc.reason)
        return

 
    if doc_id is None or claims.doc_id != doc_id:
        await _reject(
            websocket,
            CloseCode.TICKET_INVALID,
            "doc_mismatch",
            f"ticket={claims.doc_id} query={doc_id}",
        )
        return


    if not nonce_store.burn(claims.nonce):
        await _reject(websocket, CloseCode.TICKET_INVALID, "replay", claims.nonce)
        return

   
    current_role = await run_in_threadpool(_lookup_role, claims.user_id, claims.doc_id)
    if current_role is Role.NONE:
        await _reject(
            websocket, CloseCode.UNAUTHORIZED, "authz", f"user={claims.user_id}"
        )
        return

    role = (
        Role.WRITER
        if (claims.role.can_write and current_role.can_write)
        else Role.READER
    )

    logger.info(
        "ws_accept user=%s doc=%s role=%s",
        claims.user_id,
        claims.doc_id,
        role,
    )

    # Phase 2: hand off to Connection here.
    # Phase 3: join the Room for claims.doc_id.
    await websocket.close(code=CloseCode.NORMAL)
