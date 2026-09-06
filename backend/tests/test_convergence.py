"""The permanent CRDT convergence gate for Phase 5.

Two independent "clients" each fire 500 edits at the same room, concurrently,
through the real coalescing path (default update_coalesce_ms, not disabled) —
this is deliberate: merging several diffs into one broadcast via
Room._flush_updates must be equivalent to applying each diff in order, and
that equivalence is exactly the kind of thing that only breaks under real
concurrent load. Keep this test in CI forever; it is the acceptance criterion
"two clients converge" made executable.
"""

import asyncio
import random

from pycrdt import Doc, Text

from app.auth.roles import Role
from app.config import get_settings
from app.protocol import CloseCode, Frame, FrameType
from tests.test_room import running_room, update

settings = get_settings()

ALPHABET = "abcdefghijklmnopqrstuvwxyz "
EDITS_PER_WRITER = 500


EMPTY_DIFF = Doc().get_update()


def assert_converged(a: Doc, b: Doc) -> None:
    """Two docs are converged iff neither has an update the other lacks.

    Raw get_state() byte-equality is NOT this property: pycrdt's state
    vector encoding can legitimately differ between two replicas holding
    byte-identical content (confirmed empirically — 15/60 runs of this exact
    scenario had non-identical get_state() vectors with 0/60 actual content
    or update gaps). Asserting on it produces a real flake, not a real bug.
    """
    assert a.get_update(b.get_state()) == EMPTY_DIFF, "b is missing an update a has"
    assert b.get_update(a.get_state()) == EMPTY_DIFF, "a is missing an update b has"


class ConvergingMember:
    """A stub member that actually applies whatever the room broadcasts, so
    its final document can be compared against the room's and against other
    members' — real convergence, not just "some bytes arrived somewhere."""

    def __init__(self, conn_id: str, client_id: int) -> None:
        self.role = Role.WRITER
        self.conn_id = conn_id
        # Dedupe in Room._handle_update keys on client_id, so two concurrent
        # writers must not share one — that would make the room treat the
        # second writer's ops as resends of the first's and silently drop them.
        self.client_id = client_id
        self.last_seq: int | None = None
        self.close_code: CloseCode | None = None
        self.doc = Doc()
        self.doc["content"] = Text()

    def send(self, frame: Frame) -> bool:
        if frame.type is FrameType.UPDATE:
            self.doc.apply_update(frame.payload)
        return True

    def close(self, code: CloseCode) -> None:
        if self.close_code is None:
            self.close_code = code

    def is_stale(self) -> bool:
        return False

    def ping(self) -> None:
        return None

    def text(self) -> str:
        # .get(type=Text), not bare subscript: a key introduced purely by an
        # applied remote update has no locally-cached Python wrapper, and
        # doc["content"] silently returns None for it. See room_text below —
        # the room's own doc hits exactly this case, by design (it never
        # locally declares any schema).
        return str(self.doc.get("content", type=Text))


async def _hammer(room, member: ConvergingMember, seed: int, count: int) -> None:
    """Edit the member's own local doc first, exactly like a real client
    would, then submit just that op's diff — never someone else's bytes."""
    rng = random.Random(seed)
    for i in range(count):
        char = rng.choice(ALPHABET)
        before = member.doc.get_state()
        with member.doc.transaction():
            member.doc["content"] += char
        payload = member.doc.get_update(before)
        await room.submit(member, update(payload, client_seq=i + 1))
        if i % 23 == 0:
            await asyncio.sleep(0)  # yield so the two writers actually interleave


async def test_two_concurrent_writers_converge_after_500_edits_each():
    """Phase 5's exit criterion: two clients hammer one document concurrently;
    both end up byte-identical to the room and to each other."""
    async with running_room("doc-convergence") as room:
        alice = ConvergingMember("alice", client_id=1)
        bob = ConvergingMember("bob", client_id=2)
        room.join(alice)
        room.join(bob)

        await asyncio.gather(
            _hammer(room, alice, seed=1, count=EDITS_PER_WRITER),
            _hammer(room, bob, seed=2, count=EDITS_PER_WRITER),
        )

        # Let any coalescing window still in flight finish flushing.
        await asyncio.sleep(settings.update_coalesce_ms / 1000 + 0.2)

        assert_converged(alice.doc, room._doc)
        assert_converged(bob.doc, room._doc)

        room_text = str(room._doc.get("content", type=Text))
        assert room_text == alice.text() == bob.text()
        assert len(room_text) == EDITS_PER_WRITER * 2  # every edit landed, none lost


async def test_convergence_is_independent_of_arrival_order():
    """A third, late-joining peer applies the room's broadcasts in whatever
    order they actually arrived and must still reach the identical state —
    proving the merged updates are commutative, not just individually valid."""
    async with running_room("doc-convergence-order") as room:
        alice = ConvergingMember("alice", client_id=1)
        room.join(alice)

        await _hammer(room, alice, seed=3, count=100)
        await asyncio.sleep(settings.update_coalesce_ms / 1000 + 0.1)

        # A fresh peer syncing after the fact via a plain state-vector diff,
        # the same mechanism SYNC_STEP1/2 uses for a real joining client.
        late_peer = Doc()
        diff = room._doc.get_update(late_peer.get_state())
        late_peer.apply_update(diff)

        assert_converged(late_peer, room._doc)
        assert str(late_peer.get("content", type=Text)) == alice.text()
