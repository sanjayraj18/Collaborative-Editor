"""Wire protocol codec.

This module is the ONLY place in the codebase that knows the byte layout of
a frame. Nothing else may call struct.pack/unpack on wire data. See
PROTOCOL.md for the normative spec.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Final

PROTOCOL_VERSION: Final[int] = 1

HEADER_FORMAT: Final[str] = "!BQ"
HEADER_SIZE: Final[int] = struct.calcsize(HEADER_FORMAT)  # 9
MAX_SEQ: Final[int] = 2**64 - 1


class FrameType(IntEnum):
    # Control frames — JSON payload.
    CLIENT_HELLO = 0x01
    SERVER_HELLO = 0x02
    ACK = 0x03
    ERROR = 0x04
    PING = 0x05
    PONG = 0x06

    # Data frames — y-protocols binary payload.
    SYNC_STEP1 = 0x10
    SYNC_STEP2 = 0x11
    UPDATE = 0x12
    AWARENESS = 0x13


CONTROL_FRAMES: Final[frozenset[FrameType]] = frozenset(
    {
        FrameType.CLIENT_HELLO,
        FrameType.SERVER_HELLO,
        FrameType.ACK,
        FrameType.ERROR,
        FrameType.PING,
        FrameType.PONG,
    }
)


class CloseCode(IntEnum):
    NORMAL = 1000
    GOING_AWAY = 1001
    TICKET_INVALID = 4001
    PROTOCOL_ERROR = 4002
    UNAUTHORIZED = 4003
    DOC_NOT_FOUND = 4004
    SLOW_CONSUMER = 4008
    SERVER_DRAINING = 4009
    RATE_LIMITED = 4029


class ProtocolError(Exception):
    """A frame violated the spec. Carries the close code to answer with."""

    def __init__(
        self,
        message: str,
        close_code: CloseCode = CloseCode.PROTOCOL_ERROR,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.close_code = close_code


@dataclass(frozen=True, slots=True)
class Frame:

    """One wire frame. See PROTOCOL.md for the normative spec.

    `seq` on an outbound UPDATE is the room's server_seq — assigned once per
    *broadcast*, not once per inbound client frame. Phase 5 coalesces several
    client UPDATEs arriving within update_coalesce_ms into a single merged
    Yjs update and a single server_seq. A client's own edit is never echoed
    back; it learns where it landed from the ACK's server_seq instead, which
    may or may not match the seq of the next UPDATE it receives.
    """

    type: FrameType
    seq: int = 0
    payload: bytes = field(default=b"")

    # --- construction -----------------------------------------------------

    @classmethod
    def control(
        cls,
        type_: FrameType,
        data: dict[str, Any],
        *,
        seq: int = 0,
    ) -> Frame:
        if type_ not in CONTROL_FRAMES:
            raise ValueError(f"{type_.name} is not a control frame")
        encoded = json.dumps(data, separators=(",", ":")).encode("utf-8")
        return cls(type=type_, seq=seq, payload=encoded)

    @classmethod
    def data(cls, type_: FrameType, payload: bytes, *, seq: int = 0) -> Frame:
        if type_ in CONTROL_FRAMES:
            raise ValueError(f"{type_.name} is not a data frame")
        return cls(type=type_, seq=seq, payload=payload)

    # --- serialization ----------------------------------------------------

    def encode(self) -> bytes:
        if not 0 <= self.seq <= MAX_SEQ:
            raise ValueError(f"seq out of range: {self.seq}")
        return struct.pack(HEADER_FORMAT, int(self.type), self.seq) + self.payload

    def json(self) -> dict[str, Any]:
        """Decode a control frame's payload. Raises ProtocolError if malformed."""
        if self.type not in CONTROL_FRAMES:
            raise ProtocolError(f"{self.type.name} has no JSON payload")
        try:
            parsed = json.loads(self.payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolError(f"{self.type.name} payload is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ProtocolError(f"{self.type.name} payload must be a JSON object")
        return parsed

    def __repr__(self) -> str:
        return f"Frame({self.type.name}, seq={self.seq}, {len(self.payload)}B)"


def decode(raw: object, *, max_frame_bytes: int) -> Frame:
    """Parse one inbound WebSocket message. Raises ProtocolError on any violation."""
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise ProtocolError("expected a binary frame, got text")

    data = bytes(raw)

    if len(data) > max_frame_bytes:
        raise ProtocolError(f"frame too large: {len(data)} > {max_frame_bytes}")
    if len(data) < HEADER_SIZE:
        raise ProtocolError(f"frame too short: {len(data)} < {HEADER_SIZE}")

    type_code, seq = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])

    try:
        frame_type = FrameType(type_code)
    except ValueError as exc:
        raise ProtocolError(f"unknown frame type: 0x{type_code:02x}") from exc

    return Frame(type=frame_type, seq=seq, payload=data[HEADER_SIZE:])
