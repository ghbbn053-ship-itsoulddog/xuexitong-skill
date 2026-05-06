from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import time
import uuid
from typing import Any

import websockets
from websockets.server import ServerConnection

logger = logging.getLogger("xxt-bridge")


def _kill_port(port: int) -> bool:
    """尝试杀掉占用指定端口的旧进程。成功返回 True。"""
    try:
        if sys.platform == "win32":
            r = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True, timeout=5
            )
            for line in r.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.strip().split()
                    pid = parts[-1]
                    subprocess.run(
                        ["taskkill", "/PID", pid, "/F"],
                        capture_output=True, timeout=5,
                    )
                    logger.info("killed old process PID %s on port %d", pid, port)
                    return True
        else:
            r = subprocess.run(
                ["lsof", "-ti", f":{port}"], capture_output=True, text=True, timeout=5
            )
            pids = r.stdout.strip().split()
            if pids:
                for pid in pids:
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                    except OSError:
                        pass
                logger.info("killed old process(es) %s on port %d", pids, port)
                return True
    except Exception as e:
        logger.debug("_kill_port failed: %s", e)
    return False


async def _try_serve(server: BridgeServer, host: str, port: int, retry: bool = True) -> None:
    """启动 WebSocket 服务，端口冲突时自动杀旧进程重试一次。"""
    try:
        async with websockets.serve(server.handle, host, port):
            logger.info("bridge server listening on ws://%s:%d", host, port)
            await asyncio.Future()
    except OSError as e:
        if not retry:
            raise
        if "10048" in str(e) or "address already in use" in str(e).lower() or "EADDRINUSE" in str(e):
            logger.warning("port %d already in use, trying to kill old process...", port)
            if _kill_port(port):
                await asyncio.sleep(1)
                await _try_serve(server, host, port, retry=False)
                return
        raise


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
            # 扩展可能正在重连 (background.js 每 3s 自动重连), 等 10s
            logger.info("extension not connected, waiting for reconnect...")
            for i in range(10):
                await asyncio.sleep(1)
                if self._extension_ws:
                    logger.info("extension reconnected after %ds", i + 1)
                    break
        if not self._extension_ws:
            await ws.send(json.dumps({
                "error": "extension not connected, 请确保 Chrome/Edge 扩展已加载并在学习通页面"
            }))
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
    await _try_serve(server, "localhost", port)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9333)
    args = parser.parse_args()

    asyncio.run(main(args.port))
