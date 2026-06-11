from __future__ import annotations

import asyncio
import json
import logging
from contextvars import ContextVar
from typing import Any, Awaitable, Callable

from simple_agent.core.bus.envelope import (
    HandlerError,
    INVALID_PARAMS,
    INVALID_REQUEST,
    INTERNAL_ERROR,
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcSuccess,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    make_error,
)
from simple_agent.core.trace.record import TraceRecord, _now
from simple_agent.core.trace.writer import TraceWriter

logger = logging.getLogger(__name__)

_MAX_LINE_BYTES = 1024 * 1024  # 1 MB

Handler = Callable[[dict[str, Any]], Awaitable[Any]]

_writer_var: ContextVar[asyncio.StreamWriter] = ContextVar("_writer_var")


def get_connection_writer() -> asyncio.StreamWriter:
    return _writer_var.get()


class SocketServer:
    def __init__(
        self,
        host: str,
        port: int,
        trace: TraceWriter | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._handlers: dict[str, Handler] = {}
        self._server: asyncio.Server | None = None
        self._broadcaster: Any | None = None
        self._trace = trace

    def register(self, method: str, handler: Handler) -> None:
        self._handlers[method] = handler

    def set_broadcaster(self, broadcaster: Any) -> None:
        self._broadcaster = broadcaster

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
        tasks: set[asyncio.Task[None]] = set()
        while True:
            line = await reader.readline()
            if not line:
                break
            task = asyncio.create_task(self._handle_line(line, writer))
            tasks.add(task)
            task.add_done_callback(tasks.discard)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

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

        # 埋点 ①：收到命令（解析成功之后）
        if self._trace is not None:
            client_id = str(writer.get_extra_info("peername", "<unknown>"))
            self._trace.emit(
                TraceRecord(
                    ts=_now(),
                    direction="CLIENT→CORE",
                    layer="ipc",
                    kind="command",
                    client_id=client_id,
                    data={"method": req.method, "id": req.id, "params": req.params},
                )
            )

        handler = self._handlers.get(req.method)
        if handler is None:
            await self._send(
                writer,
                make_error(
                    req.id, METHOD_NOT_FOUND, f"Method not found: {req.method}"
                ),
            )
            return

        token = _writer_var.set(writer)
        try:
            result = await handler(req.params)
        except HandlerError as e:
            await self._send(
                writer,
                make_error(req.id, e.code, e.message, e.data),
            )
            return
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
        finally:
            _writer_var.reset(token)

        await self._send(
            writer, JsonRpcSuccess(id=req.id, result=result.model_dump())
        )

    async def _send(self, writer: asyncio.StreamWriter, message: Any) -> None:
        line = message.model_dump_json() + "\n"
        writer.write(line.encode())
        await writer.drain()

        # 埋点 ①：发出响应（drain 成功之后）
        if self._trace is not None:
            kind = "error" if isinstance(message, JsonRpcError) else "response"
            client_id = str(writer.get_extra_info("peername", "<unknown>"))
            data: dict[str, Any] = {}
            if isinstance(message, JsonRpcError):
                data = {
                    "id": message.id,
                    "code": message.error.code,
                    "message": message.error.message,
                }
            else:
                data = {"id": message.id}
            self._trace.emit(
                TraceRecord(
                    ts=_now(),
                    direction="CORE→CLIENT",
                    layer="ipc",
                    kind=kind,
                    client_id=client_id,
                    data=data,
                )
            )
