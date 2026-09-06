"""Resume by seq (Phase 6): exact replay, ring-overflow fallback, and dedupe.

A "reconnect" here is simulated the same way a real one happens: the old
FakeMember leaves, and a new one joins claiming the same client_id — Room has
no other way to recognize it as the same logical client. What matters is what
join() decides and sends based on that new member's last_seq.
"""

import asyncio

from app.config import get_settings
from app.protocol import FrameType
from tests.test_room import FakeMember, make_update, non_sync, running_room, update

settings = get_settings()

DOC = "22222222-2222-2222-2222-222222222222"


async def _submit_and_flush(room, sender: FakeMember, text: str, client_seq: int) -> None:
    """Force each op into its own coalescing window, so seq advances by
    exactly one per call — makes replay ranges easy to assert on."""
    await room.submit(sender, update(make_update(text), client_seq=client_seq))
    await asyncio.sleep(settings.update_coalesce_ms / 1000 + 0.02)


# --- exact replay -----------------------------------------------------------


async def test_resumed_client_receives_exactly_what_it_missed():
    async with running_room(DOC) as room:
        writer = FakeMember(conn_id="writer", client_id=10)
        watcher = FakeMember(conn_id="watcher", client_id=20)
        room.join(writer)
        room.join(watcher)

        for i in range(1, 6):
            await _submit_and_flush(room, writer, f"edit-{i}", client_seq=i)

        assert [f.seq for f in non_sync(watcher)] == [1, 2, 3, 4, 5]

        # The watcher disconnects having last applied seq 3, then reconnects.
        room.leave(watcher)
        resumer = FakeMember(conn_id="watcher-again", client_id=20, last_seq=3)
        resumed, server_seq = room.join(resumer)

        assert resumed is True
        assert server_seq == 5
        # Exactly the missed frames — no SYNC_STEP1, nothing repeated.
        assert [f.type for f in resumer.received] == [FrameType.UPDATE, FrameType.UPDATE]
        assert [f.seq for f in resumer.received] == [4, 5]


async def test_already_caught_up_resumes_with_nothing_to_replay():
    async with running_room(DOC) as room:
        writer = FakeMember(conn_id="writer", client_id=10)
        room.join(writer)
        await _submit_and_flush(room, writer, "one", client_seq=1)

        member = FakeMember(conn_id="caught-up", client_id=99, last_seq=1)
        resumed, server_seq = room.join(member)

        assert resumed is True
        assert server_seq == 1
        assert member.received == []  # nothing missed, nothing sent


# --- fallback to full sync ---------------------------------------------------


async def test_first_time_connection_gets_full_sync_not_resume():
    async with running_room(DOC) as room:
        member = FakeMember(conn_id="new", client_id=1, last_seq=None)
        resumed, server_seq = room.join(member)

        assert resumed is False
        assert server_seq == 0
        assert [f.type for f in member.received] == [FrameType.SYNC_STEP1]


async def test_client_claiming_to_be_ahead_of_us_falls_back():
    """A last_seq greater than our own is not trustworthy — full sync,
    not a guess."""
    async with running_room(DOC) as room:
        member = FakeMember(conn_id="confused", client_id=1, last_seq=999)
        resumed, server_seq = room.join(member)

        assert resumed is False
        assert server_seq == 0


async def test_falls_back_to_full_sync_when_the_gap_exceeds_the_ring(monkeypatch):
    """PROTOCOL.md §6: resume is an optimization, never a correctness
    requirement — a client that fell further behind than the ring keeps
    gets a full sync instead of a guess."""
    monkeypatch.setattr(settings, "resume_ring_size", 3)

    async with running_room(DOC) as room:
        writer = FakeMember(conn_id="writer", client_id=10)
        room.join(writer)

        for i in range(1, 8):  # 7 broadcasts; the ring only keeps the last 3
            await _submit_and_flush(room, writer, f"edit-{i}", client_seq=i)

        assert room.current_seq == 7

        resumer = FakeMember(conn_id="latecomer", client_id=30, last_seq=1)
        resumed, server_seq = room.join(resumer)

        assert resumed is False
        assert server_seq == 7
        assert [f.type for f in resumer.received] == [FrameType.SYNC_STEP1]


# --- dedupe -------------------------------------------------------------


async def test_duplicate_client_seq_is_dropped_not_reapplied():
    """A resend after a reconnect whose ACK never arrived must not burn a
    fresh server_seq or reach anyone twice."""
    async with running_room(DOC) as room:
        writer = FakeMember(conn_id="writer", client_id=10)
        watcher = FakeMember(conn_id="watcher", client_id=20)
        room.join(writer)
        room.join(watcher)

        payload = make_update("only-once")
        await room.submit(writer, update(payload, client_seq=1))
        await asyncio.sleep(settings.update_coalesce_ms / 1000 + 0.02)

        await room.submit(writer, update(payload, client_seq=1))  # the resend
        await asyncio.sleep(settings.update_coalesce_ms / 1000 + 0.02)

        assert room.current_seq == 1  # no seq burned for the resend
        assert [f.type for f in non_sync(watcher)] == [FrameType.UPDATE]
        assert [f.type for f in non_sync(writer)] == [FrameType.ACK]
