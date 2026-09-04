"""Minimal CLI client for the collab WebSocket.

Your only test surface until the browser client lands in Phase 7.

    uv run python scripts/probe.py "ws://localhost:8000/ws?doc=<id>&ticket=<t>"

Flags:
    --no-hello    skip CLIENT_HELLO, to watch the server close with 4002
    --silent      connect and send nothing, to watch the 5s HELLO deadline fire
"""

import asyncio
import json
import random
import sys

import websockets

from app.config import get_settings
from app.protocol import PROTOCOL_VERSION, Frame, FrameType, decode

settings = get_settings()
ORIGIN = settings.allowed_origins[0] if settings.allowed_origins else "http://localhost:5173"
MAX = settings.max_frame_bytes


async def main(url: str, *, hello: bool = True, silent: bool = False) -> None:
    print(f"connecting  origin={ORIGIN}")

    async with websockets.connect(url, origin=ORIGIN) as ws:
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

        payload = b"hello"
        out = Frame.data(FrameType.UPDATE, payload)
        print(f"  -> {out} {payload!r}")
        await ws.send(out.encode())

        back = decode(await asyncio.wait_for(ws.recv(), timeout=5), max_frame_bytes=MAX)
        print(f"  <- {back} {back.payload!r}")

        print("\nechoed correctly" if back.payload == payload else "\npayload did not match")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)

    try:
        asyncio.run(main(
            args[0],
            hello="--no-hello" not in sys.argv,
            silent="--silent" in sys.argv,
        ))
    except websockets.exceptions.InvalidStatus as exc:
        print(f"handshake rejected: {exc}")
    except websockets.exceptions.ConnectionClosed as exc:
        print(f"closed by server: code={exc.code} reason={exc.reason!r}")
    except TimeoutError:
        print("no reply in time")
