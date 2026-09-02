import pytest

from app.protocol import (
    HEADER_SIZE,
    CloseCode,
    Frame,
    FrameType,
    ProtocolError,
    decode,
)

MAX = 1024 * 1024


def test_header_is_nine_bytes():
    assert HEADER_SIZE == 9


def test_data_frame_round_trip():
    original = Frame.data(FrameType.UPDATE, b"\x01\x02\x03", seq=42)
    decoded = decode(original.encode(), max_frame_bytes=MAX)

    assert decoded.type is FrameType.UPDATE
    assert decoded.seq == 42
    assert decoded.payload == b"\x01\x02\x03"


def test_control_frame_round_trip():
    original = Frame.control(
        FrameType.CLIENT_HELLO,
        {"protocol": 1, "client_id": 7, "last_seq": None},
    )
    decoded = decode(original.encode(), max_frame_bytes=MAX)

    assert decoded.type is FrameType.CLIENT_HELLO
    assert decoded.json() == {"protocol": 1, "client_id": 7, "last_seq": None}


def test_large_seq_survives_round_trip():
    original = Frame.data(FrameType.UPDATE, b"", seq=2**63 + 5)
    assert decode(original.encode(), max_frame_bytes=MAX).seq == 2**63 + 5


def test_empty_payload_is_legal():
    decoded = decode(Frame.data(FrameType.SYNC_STEP1, b"").encode(), max_frame_bytes=MAX)
    assert decoded.payload == b""


def test_text_frame_rejected():
    with pytest.raises(ProtocolError, match="binary"):
        decode("hello", max_frame_bytes=MAX)


def test_truncated_frame_rejected():
    with pytest.raises(ProtocolError, match="too short"):
        decode(b"\x12\x00", max_frame_bytes=MAX)


def test_oversized_frame_rejected():
    with pytest.raises(ProtocolError, match="too large"):
        decode(b"\x00" * 100, max_frame_bytes=50)


def test_unknown_frame_type_rejected():
    with pytest.raises(ProtocolError, match="unknown frame type"):
        decode(b"\xff" + b"\x00" * 8, max_frame_bytes=MAX)


def test_protocol_error_defaults_to_4002():
    with pytest.raises(ProtocolError) as exc_info:
        decode("hello", max_frame_bytes=MAX)
    assert exc_info.value.close_code is CloseCode.PROTOCOL_ERROR


def test_malformed_json_in_control_frame():
    bad = Frame(type=FrameType.CLIENT_HELLO, seq=0, payload=b"{not json")
    with pytest.raises(ProtocolError, match="valid JSON"):
        bad.json()


def test_json_array_payload_rejected():
    bad = Frame(type=FrameType.CLIENT_HELLO, seq=0, payload=b"[1,2,3]")
    with pytest.raises(ProtocolError, match="JSON object"):
        bad.json()


def test_control_constructor_rejects_data_frame():
    with pytest.raises(ValueError):
        Frame.control(FrameType.UPDATE, {"a": 1})


def test_data_constructor_rejects_control_frame():
    with pytest.raises(ValueError):
        Frame.data(FrameType.PING, b"x")
