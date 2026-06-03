from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

from simple_agent.core.bus.envelope import EventPushEnvelope, JsonRpcError, JsonRpcRequest

logger = logging.getLogger(__name__)

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class IpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"IpcError({code}): {message}")


class SocketClient:
    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._event_handlers: list[EventHandler] = []
        self._running = False

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(
            self._host, self._port
        )

    def on_event(self, handler: EventHandler) -> None:
        self._event_handlers.append(handler)

    async def send_command(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if self._writer is None:
            raise RuntimeError("not connected")

        req_id = f"req-{id(asyncio.current_task())}-{asyncio.get_event_loop().time()}"
        req = JsonRpcRequest(id=req_id, method=method, params=params or {})
        line = req.model_dump_json() + "\n"
        self._writer.write(line.encode())
        await self._writer.drain()

        fut: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending[req_id] = fut
        try:
            return await fut
        finally:
            self._pending.pop(req_id, None)

    async def run_event_loop(self) -> None:
        if self._reader is None:
            raise RuntimeError("not connected")
        self._running = True
        try:
            while self._running:
                line = await self._reader.readline()
                if not line:
                    break
                await self._dispatch(line)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug("SocketClient event loop error: %s", e)
        finally:
            self._running = False
            self._cancel_all_pending()

    async def _dispatch(self, line: bytes) -> None:
        msg = json.loads(line)

        if "jsonrpc" in msg:
            req_id = msg.get("id")
            if req_id and req_id in self._pending:
                fut = self._pending.pop(req_id)
                if "error" in msg:
                    err = msg["error"]
                    fut.set_exception(IpcError(err["code"], err["message"]))
                else:
                    fut.set_result(msg.get("result") or {})

        elif msg.get("kind") == "event":
            event_data = msg.get("event", {})
            for handler in self._event_handlers:
                try:
                    await handler(event_data)
                except Exception as e:
                    logger.exception("Event handler error: %s", e)

    def _cancel_all_pending(self) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()

    async def close(self) -> None:
        self._running = False
        self._cancel_all_pending()
        if self._writer is not None:
            self._writer.close()
            await self._writer.wait_closed()
            self._writer = None
            self._reader = None
