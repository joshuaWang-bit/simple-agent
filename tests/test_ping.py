from __future__ import annotations

import asyncio
import json
import time

import pytest

from simple_agent import __version__
from simple_agent.core.bus.commands import PongResult
from simple_agent.core.bus.envelope import (
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    JsonRpcError,
    JsonRpcSuccess,
)
from simple_agent.core.config import AgentConfig
from simple_agent.core.transport.socket_server import SocketServer


@pytest.fixture
def config() -> AgentConfig:
    return AgentConfig(host="127.0.0.1", port=17437)


async def _send_line(reader, writer, obj: dict) -> dict:
    writer.write((json.dumps(obj) + "\n").encode())
    await writer.drain()
    line = await asyncio.wait_for(reader.readline(), timeout=5.0)
    return json.loads(line)


@pytest.mark.asyncio
async def test_ping_e2e(config: AgentConfig) -> None:
    """End-to-end test: start server, send ping, verify response."""
    start_time = time.monotonic()

    async def ping_handler(params: dict) -> PongResult:
        return PongResult(
            server_version=__version__,
            uptime_ms=int((time.monotonic() - start_time) * 1000),
            received_at="2026-06-02T09:00:00",
        )

    server = SocketServer(config.host, config.port)
    server.register("core.ping", ping_handler)
    await server.start()

    reader, writer = await asyncio.open_connection(config.host, config.port)
    raw = await _send_line(
        reader,
        writer,
        {
            "jsonrpc": "2.0",
            "id": "test-1",
            "method": "core.ping",
            "params": {"client": "test"},
        },
    )
    resp = JsonRpcSuccess.model_validate(raw)
    result = PongResult.model_validate(resp.result)

    assert result.server_version == __version__
    assert result.uptime_ms >= 0
    assert result.received_at

    writer.close()
    await writer.wait_closed()
    await server.stop()


@pytest.mark.asyncio
async def test_parse_error(config: AgentConfig) -> None:
    """Invalid JSON should return PARSE_ERROR."""
    server = SocketServer(config.host, config.port)
    await server.start()

    reader, writer = await asyncio.open_connection(config.host, config.port)
    writer.write(b"not json\n")
    await writer.drain()
    raw = json.loads(await asyncio.wait_for(reader.readline(), timeout=5.0))
    err = JsonRpcError.model_validate(raw)

    assert err.error.code == PARSE_ERROR

    writer.close()
    await writer.wait_closed()
    await server.stop()


@pytest.mark.asyncio
async def test_invalid_request(config: AgentConfig) -> None:
    """Missing required fields should return INVALID_REQUEST."""
    server = SocketServer(config.host, config.port)
    await server.start()

    reader, writer = await asyncio.open_connection(config.host, config.port)
    raw = await _send_line(reader, writer, {"jsonrpc": "2.0"})
    err = JsonRpcError.model_validate(raw)

    assert err.error.code == INVALID_REQUEST

    writer.close()
    await writer.wait_closed()
    await server.stop()


@pytest.mark.asyncio
async def test_method_not_found(config: AgentConfig) -> None:
    """Unknown method should return METHOD_NOT_FOUND."""
    server = SocketServer(config.host, config.port)
    await server.start()

    reader, writer = await asyncio.open_connection(config.host, config.port)
    raw = await _send_line(
        reader,
        writer,
        {
            "jsonrpc": "2.0",
            "id": "test-1",
            "method": "core.unknown",
            "params": {},
        },
    )
    err = JsonRpcError.model_validate(raw)

    assert err.error.code == METHOD_NOT_FOUND

    writer.close()
    await writer.wait_closed()
    await server.stop()


@pytest.mark.asyncio
async def test_connection_requests_run_concurrently(config: AgentConfig) -> None:
    """A long request must not block a later request on the same connection."""
    gate = asyncio.Event()

    async def slow_handler(params: dict) -> PongResult:
        await gate.wait()
        return PongResult(
            server_version=__version__,
            uptime_ms=1,
            received_at="slow",
        )

    async def fast_handler(params: dict) -> PongResult:
        gate.set()
        return PongResult(
            server_version=__version__,
            uptime_ms=1,
            received_at="fast",
        )

    server = SocketServer(config.host, config.port)
    server.register("test.slow", slow_handler)
    server.register("test.fast", fast_handler)
    await server.start()

    reader, writer = await asyncio.open_connection(config.host, config.port)
    try:
        writer.write(
            (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "slow",
                        "method": "test.slow",
                        "params": {},
                    }
                )
                + "\n"
            ).encode()
        )
        writer.write(
            (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "fast",
                        "method": "test.fast",
                        "params": {},
                    }
                )
                + "\n"
            ).encode()
        )
        await writer.drain()

        first = json.loads(await asyncio.wait_for(reader.readline(), timeout=1.0))
        second = json.loads(await asyncio.wait_for(reader.readline(), timeout=1.0))

        assert first["id"] == "fast"
        assert second["id"] == "slow"
    finally:
        gate.set()
        writer.close()
        await writer.wait_closed()
        await server.stop()


@pytest.mark.asyncio
async def test_port_probe(config: AgentConfig) -> None:
    """Starting a second server on the same port should exit."""
    server1 = SocketServer(config.host, config.port)
    await server1.start()

    server2 = SocketServer(config.host, config.port)
    with pytest.raises(SystemExit):
        await server2.start()

    await server1.stop()
