import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.auth.roles import Role
from app.auth.tickets import issue
from app.config import get_settings
from app.main import app
from app.protocol import CloseCode

settings = get_settings()
ORIGIN = {"origin": "http://localhost:5173"}

# No `with` block: we do not want lifespan (and its create_all) to run, so
# these tests stay independent of the database.
client = TestClient(app)

USER = "11111111-1111-1111-1111-111111111111"
DOC = "22222222-2222-2222-2222-222222222222"


def make_ticket(user_id=USER, doc_id=DOC, role=Role.WRITER, ttl=30):
    ticket, _ = issue(
        user_id=user_id,
        doc_id=doc_id,
        role=role,
        secret=settings.secret_key,
        ttl_seconds=ttl,
    )
    return ticket


def close_code_for(url: str, headers=ORIGIN) -> int:
    """Connect, expect to be closed, return the close code."""
    with client.websocket_connect(url, headers=headers) as ws:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            ws.receive_text()
    return exc_info.value.code


# --- 1. origin: rejected before the handshake completes -------------------


@pytest.mark.parametrize(
    "headers",
    [
        {"origin": "http://evil.com"},
        {"origin": "http://localhost:5173.evil.com"},
        {"origin": "null"},
        {},  # no Origin header at all
    ],
)
def test_bad_origin_never_upgrades(headers):
    ticket = make_ticket()
    with pytest.raises(Exception):
        with client.websocket_connect(
            f"/ws?doc={DOC}&ticket={ticket}", headers=headers
        ):
            pass


# --- 2. ticket signature and expiry --------------------------------------


@pytest.mark.parametrize("ticket", ["", "garbage", "v1.aaa.bbb", "a.b.c.d"])
def test_bad_ticket_closes_4001(ticket):
    assert close_code_for(f"/ws?doc={DOC}&ticket={ticket}") == CloseCode.TICKET_INVALID


def test_missing_ticket_param_closes_4001():
    assert close_code_for(f"/ws?doc={DOC}") == CloseCode.TICKET_INVALID


def test_expired_ticket_closes_4001():
    ticket = make_ticket(ttl=-1)
    assert close_code_for(f"/ws?doc={DOC}&ticket={ticket}") == CloseCode.TICKET_INVALID


def test_forged_ticket_closes_4001():
    ticket = make_ticket()
    version, payload, _ = ticket.split(".")
    forged = f"{version}.{payload}.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    assert close_code_for(f"/ws?doc={DOC}&ticket={forged}") == CloseCode.TICKET_INVALID


# --- 3. the ticket must name the document being opened -------------------


def test_ticket_for_another_document_closes_4001():
    ticket = make_ticket(doc_id="33333333-3333-3333-3333-333333333333")
    assert close_code_for(f"/ws?doc={DOC}&ticket={ticket}") == CloseCode.TICKET_INVALID


def test_missing_doc_param_closes_4001():
    ticket = make_ticket()
    assert close_code_for(f"/ws?ticket={ticket}") == CloseCode.TICKET_INVALID


# --- 4. single use --------------------------------------------------------


def test_replayed_ticket_closes_4001():
    """First use gets past the nonce and fails authz; the second is a replay."""
    ticket = make_ticket()
    url = f"/ws?doc={DOC}&ticket={ticket}"

    first = close_code_for(url)
    second = close_code_for(url)

    assert first == CloseCode.UNAUTHORIZED      # burned, then denied by authz
    assert second == CloseCode.TICKET_INVALID   # never reaches authz again


# --- 5. authorization -----------------------------------------------------


def test_unknown_document_closes_4003():
    """A valid ticket whose document does not exist: 4003, never 4001."""
    ticket = make_ticket()
    assert close_code_for(f"/ws?doc={DOC}&ticket={ticket}") == CloseCode.UNAUTHORIZED
