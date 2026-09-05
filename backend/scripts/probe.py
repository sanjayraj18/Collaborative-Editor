"""Minimal CLI client for the collab WebSocket.

Your only test surface until the browser client lands in Phase 7.

    uv run python scripts/probe.py "ws://localhost:8000/ws?doc=<id>&ticket=<t>"

Flags:
    --no-hello    skip CLIENT_HELLO, to watch the server close with 4002
    --silent      connect and send nothing, to watch the 5s HELLO deadline fire
    --flood       send continuously without reading, to watch backpressure evict us
    --listen      stay connected and print everything the room sends us
    --text=WORDS  payload to send instead of "hello"
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

from app.config import get_settings
from app.protocol import PROTOCOL_VERSION, Frame, FrameType, decode

settings = get_settings()
ORIGIN = settings.allowed_origins[0] if settings.allowed_origins else "http://localhost:5173"
MAX = settings.max_frame_bytes


async def _flood(ws, seconds: float, size: int = 64 * 1024) -> None:
    """Send hard while reading nothing, so our echoes pile up server-side.

    max_queue=1 on the connection means the client library stops draining the
    socket almost immediately, TCP backpressures the server's writer, and the
    send queue fills.
    """
    raw = Frame.data(FrameType.UPDATE, b"x" * size).encode()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + seconds
    sent = 0

    print(f"flooding {size // 1024} KiB frames for {seconds:.0f}s, reading nothing...")
    try:
        while loop.time() < deadline:
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


async def _listen(ws) -> None:
    """Sit in the room and print whatever arrives. Ctrl-C to stop."""
    print("listening — run another probe on the same doc to see its edits\n")
    while True:
        frame = decode(await ws.recv(), max_frame_bytes=MAX)
        detail = frame.json() if frame.type in (FrameType.ACK,) else frame.payload[:60]
        print(f"  <- {frame} {detail!r}")


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

        if listen:
            await _listen(ws)
            return

        # The room does not echo to the sender — it answers with an ACK
        # carrying the sequence number it assigned. PROTOCOL.md §4.
        payload = text.encode()
        out = Frame.data(FrameType.UPDATE, payload, seq=1)
        print(f"  -> {out} {payload!r}")
        await ws.send(out.encode())

        back = decode(await asyncio.wait_for(ws.recv(), timeout=5), max_frame_bytes=MAX)

        if back.type is FrameType.ACK:
            acked = back.json()
            print(f"  <- ACK client_seq={acked['client_seq']} server_seq={acked['server_seq']}")
            print(f"\nacked at server_seq {acked['server_seq']}")
        else:
            print(f"  <- {back} {back.payload!r}")
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
