from __future__ import annotations

import asyncio
import json
import logging
from contextvars import ContextVar
from typing import Any, Awaitable, Callable

from simple_agent.core.bus.envelope import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    INTERNAL_ERROR,
    JsonRpcRequest,
    JsonRpcSuccess,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    make_error,
)

logger = logging.getLogger(__name__)

_MAX_LINE_BYTES = 1024 * 1024  # 1 MB

Handler = Callable[[dict[str, Any]], Awaitable[Any]]

_writer_var: ContextVar[asyncio.StreamWriter] = ContextVar("_writer_var")


def get_connection_writer() -> asyncio.StreamWriter:
    return _writer_var.get()


class SocketServer:
    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._handlers: dict[str, Handler] = {}
        self._server: asyncio.Server | None = None

    def register(self, method: str, handler: Handler) -> None:
        self._handlers[method] = handler

    async def start(self) -> str:
        # 探活：如果端口已能被连接，说明已有 daemon 在跑
        try:
            _r, w = await asyncio.open_connection(self._host, self._port)
            w.close()
            await w.wait_closed()
            raise SystemExit(f"core already running at {self._host}:{self._port}")
        except (ConnectionRefusedError, OSError):
            pass

        self._server = await asyncio.start_server(
            self._handle_connection,
            host=self._host,
            port=self._port,
            limit=_MAX_LINE_BYTES,
        )
        return f"{self._host}:{self._port}"

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._handlers: dict[str, Handler] = {}
        self._server: asyncio.Server | None = None
        self._broadcaster: Any | None = None

    def set_broadcaster(self, broadcaster: Any) -> None:
        self._broadcaster = broadcaster

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        addr = writer.get_extra_info("peername")
        logger.debug("Client connected: %s", addr)
        try:
            await self._read_loop(reader, writer)
        finally:
            if self._broadcaster is not None:
                self._broadcaster.unsubscribe(writer)
            writer.close()
            await writer.wait_closed()
            logger.debug("Client disconnected: %s", addr)

    async def _read_loop(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        while True:
            line = await reader.readline()
            if not line:
                return
            await self._handle_line(line, writer)

    async def _handle_line(self, line: bytes, writer: asyncio.StreamWriter) -> None:
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as e:
            await self._send(
                writer, make_error(None, PARSE_ERROR, f"Parse error: {e}")
            )
            return

        try:
            req = JsonRpcRequest.model_validate(raw)
        except Exception as e:
            await self._send(
                writer,
                make_error(None, INVALID_REQUEST, "Invalid Request", str(e)),
            )
            return

        handler = self._handlers.get(req.method)
        if handler is None:
            await self._send(
                writer,
                make_error(
                    req.id, METHOD_NOT_FOUND, f"Method not found: {req.method}"
                ),
            )
            return

        try:
            _writer_var.set(writer)
            result = await handler(req.params)
        except Exception as e:
            from pydantic import ValidationError

            if isinstance(e, ValidationError):
                await self._send(
                    writer,
                    make_error(req.id, INVALID_PARAMS, "Invalid params", str(e)),
                )
            else:
                logger.exception("Handler error for %s", req.method)
                await self._send(
                    writer,
                    make_error(req.id, INTERNAL_ERROR, "Internal error"),
                )
            return

        await self._send(
            writer, JsonRpcSuccess(id=req.id, result=result.model_dump())
        )

    async def _send(self, writer: asyncio.StreamWriter, message: Any) -> None:
        line = message.model_dump_json() + "\n"
        writer.write(line.encode())
        await writer.drain()
