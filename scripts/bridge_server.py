from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from typing import Any

import websockets
from websockets.server import ServerConnection

logger = logging.getLogger("xxt-bridge")


class BridgeServer:
    def __init__(self) -> None:
        self._extension_ws: ServerConnection | None = None
        self._pending: dict[str, asyncio.Future[Any]] = {}

    async def handle(self, ws: ServerConnection) -> None:
        raw = await ws.recv()
        msg = json.loads(raw)
        role = msg.get("role")

        if role == "extension":
            await self._handle_extension(ws)
            return

        if role == "cli":
            await self._handle_cli(ws, msg)
            return

        await ws.send(json.dumps({"error": f"unknown role: {role}"}))

    async def _handle_extension(self, ws: ServerConnection) -> None:
        self._extension_ws = ws
        try:
            async for raw in ws:
                msg = json.loads(raw)
                msg_id = msg.get("id")
                if msg_id and msg_id in self._pending:
                    future = self._pending.pop(msg_id)
                    if not future.done():
                        future.set_result(msg)
        finally:
            self._extension_ws = None
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("extension disconnected"))
            self._pending.clear()

    async def _handle_cli(self, ws: ServerConnection, msg: dict[str, Any]) -> None:
        if msg.get("method") == "ping_server":
            await ws.send(json.dumps({
                "result": {"extension_connected": self._extension_ws is not None}
            }))
            return

        if not self._extension_ws:
            await ws.send(json.dumps({"error": "extension not connected"}))
            return

        msg_id = str(uuid.uuid4())
        msg["id"] = msg_id
        future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = future

        await self._extension_ws.send(json.dumps(msg))

        try:
            result = await asyncio.wait_for(future, timeout=60)
            await ws.send(json.dumps(result))
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            await ws.send(json.dumps({"error": "command timeout"}))


async def main(port: int) -> None:
    server = BridgeServer()
    async with websockets.serve(server.handle, "localhost", port):
        logger.info("bridge server listening on ws://localhost:%d", port)
        await asyncio.Future()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9333)
    args = parser.parse_args()

    asyncio.run(main(args.port))
