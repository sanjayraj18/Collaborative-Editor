"""Minimal CLI client for the collab WebSocket.

Your only test surface until the browser client lands in Phase 7. Speaks real
Yjs updates via pycrdt, so it actually performs the sync handshake and can
prove two probes converge on the same text — not just that bytes echo.

    uv run python scripts/probe.py "ws://localhost:8000/ws?doc=<id>&ticket=<t>"

Flags:
    --no-hello    skip CLIENT_HELLO, to watch the server close with 4002
    --silent      connect and send nothing, to watch the 5s HELLO deadline fire
    --flood       send continuously without reading, to watch backpressure evict us
    --listen      stay connected, sync, and print every frame + the converged text
    --text=WORDS  insert this text after syncing, instead of "hello"
"""

import asyncio
import json
import pathlib
import random
import sys

# Running "python scripts/probe.py" puts scripts/ on sys.path, not the project
# root, so "app" would not import. Put the root first.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import websockets
from pycrdt import Doc, Text

from app.config import get_settings
from app.protocol import PROTOCOL_VERSION, Frame, FrameType, decode

settings = get_settings()
ORIGIN = settings.allowed_origins[0] if settings.allowed_origins else "http://localhost:5173"
MAX = settings.max_frame_bytes


class YjsClient:
    """A local pycrdt.Doc that performs the sync handshake in PROTOCOL.md §5
    step 4b, so this probe's document genuinely converges with the server's
    instead of just sending opaque bytes."""

    def __init__(self) -> None:
        self.doc = Doc()
        self.doc["content"] = Text()

    async def sync(self, ws) -> None:
        """Consume the server's opening SYNC_STEP1, answer it, and apply
        whatever the server sends back."""
        step1 = decode(await asyncio.wait_for(ws.recv(), timeout=5), max_frame_bytes=MAX)
        if step1.type is not FrameType.SYNC_STEP1:
            print(f"  (expected SYNC_STEP1, got {step1} — skipping sync)")
            return

        # Tell the server what we're missing relative to our own (empty) state.
        diff_for_server = self.doc.get_update(step1.payload)
        await ws.send(Frame.data(FrameType.SYNC_STEP2, diff_for_server).encode())

        # Offer our own state vector so the server can tell us what it has
        # that we don't — the other half of PROTOCOL.md's full-sync exchange.
        await ws.send(Frame.data(FrameType.SYNC_STEP1, self.doc.get_state()).encode())

        step2 = decode(await asyncio.wait_for(ws.recv(), timeout=5), max_frame_bytes=MAX)
        if step2.type is FrameType.SYNC_STEP2:
            self.doc.apply_update(step2.payload)
        else:
            print(f"  (expected SYNC_STEP2 back, got {step2} — doc may already be empty)")

    def make_edit(self, text: str) -> bytes:
        """Insert text locally; return the update representing just this op."""
        before = self.doc.get_state()
        with self.doc.transaction():
            self.doc["content"] += text
        return self.doc.get_update(before)

    def text(self) -> str:
        # .get(type=Text), not bare subscript: after applying a remote diff
        # that introduces 'content', this doc has no locally-cached Python
        # wrapper for the key, and doc["content"] silently returns None.
        return str(self.doc.get("content", type=Text))


async def _flood(ws, seconds: float) -> None:
    """Send valid UPDATEs hard while reading nothing.

    The payload no longer needs to be large: Room._handle_update now calls
    apply_update() on every frame, so garbage bytes get rejected with 4002
    before backpressure ever has a chance to build. What actually fills our
    own send queue is the ACK the room replies with per submitted frame —
    real backpressure, just driven by acknowledgements instead of an echo.
    """
    doc = Doc()
    doc["content"] = Text()
    with doc.transaction():
        doc["content"] += "x"
    single_update = doc.get_update()

    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    sent = 0

    print(f"flooding valid UPDATE frames for {seconds:.0f}s, reading nothing...")
    try:
        while loop.time() < deadline:
            raw = Frame.data(FrameType.UPDATE, single_update, seq=sent + 1).encode()
            await ws.send(raw)
            sent += 1
            if sent % 50 == 0:
                await asyncio.sleep(0)
        print(f"sent {sent} frames; still connected — waiting for the server...")
        await asyncio.wait_for(ws.wait_closed(), timeout=15)
    except websockets.exceptions.ConnectionClosed as exc:
        print(f"\nsent {sent} frames before the server closed us")
        print(f"closed: code={exc.code} reason={exc.reason!r}")
        return

    print(f"closed: code={ws.close_code} reason={ws.close_reason!r}")


async def _listen(ws, client: YjsClient) -> None:
    """Sit in the room, apply what arrives, and print the converged text.
    Ctrl-C to stop."""
    print("listening — run another probe on the same doc to watch it converge\n")
    while True:
        frame = decode(await ws.recv(), max_frame_bytes=MAX)

        if frame.type is FrameType.UPDATE:
            client.doc.apply_update(frame.payload)
            print(f"  <- {frame}  doc now: {client.text()!r}")
        elif frame.type is FrameType.ACK:
            print(f"  <- {frame} {frame.json()}")
        elif frame.type is FrameType.AWARENESS:
            print(f"  <- {frame} (awareness, {len(frame.payload)}B)")
        else:
            print(f"  <- {frame}")


async def main(url: str, *, hello: bool = True, silent: bool = False,
               flood: bool = False, listen: bool = False,
               text: str = "hello") -> None:
    print(f"connecting  origin={ORIGIN}")

    async with websockets.connect(url, origin=ORIGIN, max_queue=1) as ws:
        print("connected")

        if silent:
            print(f"sending nothing — expecting close in ~{settings.hello_timeout_seconds}s")
            await ws.wait_closed()
            return

        if hello:
            client_id = random.getrandbits(32)
            out = Frame.control(
                FrameType.CLIENT_HELLO,
                {"protocol": PROTOCOL_VERSION, "client_id": client_id, "last_seq": None},
            )
            print(f"  -> CLIENT_HELLO client_id={client_id}")
            await ws.send(out.encode())

            reply = decode(await asyncio.wait_for(ws.recv(), timeout=5), max_frame_bytes=MAX)
            if reply.type is not FrameType.SERVER_HELLO:
                print(f"  <- unexpected {reply}")
                return
            print(f"  <- SERVER_HELLO {json.dumps(reply.json(), indent=6)}")

        if flood:
            await _flood(ws, settings.slow_consumer_grace_seconds + 4)
            return

        client = YjsClient()
        await client.sync(ws)
        print(f"  synced — local doc so far: {client.text()!r}")

        if listen:
            await _listen(ws, client)
            return

        # The room does not echo to a solo sender — it answers with an ACK
        # carrying the sequence number it assigned. PROTOCOL.md §4.
        payload = client.make_edit(text)
        out = Frame.data(FrameType.UPDATE, payload, seq=1)
        print(f"  -> {out} insert={text!r}")
        await ws.send(out.encode())

        back = decode(await asyncio.wait_for(ws.recv(), timeout=5), max_frame_bytes=MAX)

        if back.type is FrameType.ACK:
            acked = back.json()
            print(f"  <- ACK client_seq={acked['client_seq']} server_seq={acked['server_seq']}")
            print(f"\nacked at server_seq {acked['server_seq']}; local doc now: {client.text()!r}")
        else:
            print(f"  <- {back}")
            print("\nexpected an ACK")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)

    try:
        asyncio.run(main(
            args[0],
            hello="--no-hello" not in sys.argv,
            silent="--silent" in sys.argv,
            flood="--flood" in sys.argv,
            listen="--listen" in sys.argv,
            text=next(
                (a.split("=", 1)[1] for a in sys.argv if a.startswith("--text=")),
                "hello",
            ),
        ))
    except KeyboardInterrupt:
        print("\nstopped")
    except websockets.exceptions.InvalidStatus as exc:
        print(f"handshake rejected: {exc}")
    except websockets.exceptions.ConnectionClosed as exc:
        print(f"closed by server: code={exc.code} reason={exc.reason!r}")
    except TimeoutError:
        print("no reply in time")
