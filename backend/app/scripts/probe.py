import asyncio
from fastapi import WebSocket
from app.protocol import Frame, FrameType, decode


async def main(url : str) -> None:
    async with websockets.connect(url, origin="http://localhost:5173") as ws:
        await ws.send(Frame.data(FrameType.UPDATE, b"hello").encode())
        reply = decode(await ws.recv(), max_frame_bytes=1 << 20)
        print("got back:", reply, reply.payload)