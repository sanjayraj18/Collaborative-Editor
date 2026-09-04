

import asyncio
import sys

import websockets

from app.config import get_settings
from app.protocol import Frame, FrameType, decode

settings = get_settings()
ORIGIN = settings.allowed_origins[0] if settings.allowed_origins else "http://localhost:5173"


async def main(url: str) -> None:
    print(f"connecting  origin={ORIGIN}")
    try:
        async with websockets.connect(url, origin=ORIGIN) as ws:
            print("connected")

            out = Frame.data(FrameType.UPDATE, b"hello")
            print(f"  -> {out} {out.payload!r}")
            await ws.send(out.encode())

            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            back = decode(raw, max_frame_bytes=settings.max_frame_bytes)
            print(f"  <- {back} {back.payload!r}")

            if back.payload == out.payload:
                print("\nechoed correctly")
            else:
                print("\npayload did not match")

    except websockets.exceptions.InvalidStatus as exc:
        print(f"handshake rejected: {exc}")
    except websockets.exceptions.ConnectionClosed as exc:
        print(f"closed by server: code={exc.code} reason={exc.reason!r}")
    except TimeoutError:
        print("no reply within 5s")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1]))
