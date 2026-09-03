import base64
from dataclasses import dataclass
import json
import hmac
import time
import secrets
from app.auth.roles import Role
from typing import Final
from hashlib import sha256


TICKET_VERSION: Final[str] = "v1"
NONCE_BYTES: Final[int] = 16
MAX_TICKET_LENGTH: Final[int] = 1024


class TicketError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class TicketClaims:
    user_id: str
    doc_id: str
    role: Role
    nonce: str
    expires_at: int



def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _sign(signing_input: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        signing_input.encode("ascii"),
        sha256,
    ).digest()
    return _b64url_encode(digest)



def issue(*,user_id : str, doc_id : str, secret : str, role : Role, ttl_seconds:int , now :float|None = None) -> tuple[str, int]:

    if role is Role.NONE:
        raise ValueError("refusing to issue a ticket for Role.NONE")

    issued_at = int(time.time() if now is None else now)
    expires_at = issued_at + ttl_seconds

    payload = {
        "u" : user_id,
        "d" : doc_id,
        "r" : str(role),
        "n" : secrets.token_urlsafe(NONCE_BYTES),
        "e" : expires_at,
    }
    payload_b64 = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )

    signing_input = f"{TICKET_VERSION}.{payload_b64}"

    return f"{signing_input}.{_sign(signing_input, secret)}", expires_at



def verify( ticket: str | None, *,secret: str,now: float | None = None) -> TicketClaims:
 
    current_time = int(time.time() if now is None else now)

    if not ticket:
        raise TicketError("missing ticket")
    if len(ticket) > MAX_TICKET_LENGTH:
        raise TicketError(f"oversized ticket: {len(ticket)} bytes")

    parts = ticket.split(".")
    if len(parts) != 3:
        raise TicketError(f"malformed ticket: {len(parts)} segments, expected 3")

    version, payload_b64, signature = parts
    if version != TICKET_VERSION:
        raise TicketError(f"unsupported ticket version: {version!r}")

    expected = _sign(f"{version}.{payload_b64}", secret)
    if not hmac.compare_digest(expected, signature):
        raise TicketError("bad signature")


    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except ValueError as exc:
        raise TicketError("payload is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise TicketError("payload is not a JSON object")

    try:
        claims = TicketClaims(
            user_id=str(payload["u"]),
            doc_id=str(payload["d"]),
            role=Role(payload["r"]),
            nonce=str(payload["n"]),
            expires_at=int(payload["e"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise TicketError("payload has missing or invalid fields") from exc

    if claims.expires_at <= current_time:
        raise TicketError("ticket expired")

    return claims