from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from simple_agent.core.bus.envelope import JsonRpcError, JsonRpcSuccess
from simple_agent.core.transport.socket_client import IpcError, SocketClient


def _get_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def free_port() -> int:
    return _get_free_port()


async def _start_server(
    port: int,
    handler: Any | None = None,
) -> asyncio.Server:
    async def default_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                msg = json.loads(line)
                req_id = msg.get("id")
                method = msg.get("method")

                if handler:
                    await handler(msg, writer)
                elif method == "event.subscribe":
                    resp = JsonRpcSuccess(id=req_id, result={"subscription_id": "sub-abc", "replayed_count": 0})
                    writer.write((resp.model_dump_json() + "\n").encode())
                    await writer.drain()
                elif method == "agent.run":
                    resp = JsonRpcSuccess(id=req_id, result={"run_id": "20260515-abc"})
                    writer.write((resp.model_dump_json() + "\n").encode())
                    await writer.drain()
                    # Push some events
                    for ev in [
                        {"kind": "event", "event": {"type": "run.started", "run_id": "20260515-abc"}},
                        {"kind": "event", "event": {"type": "run.finished", "run_id": "20260515-abc", "status": "success"}},
                    ]:
                        writer.write((json.dumps(ev) + "\n").encode())
                        await writer.drain()
                else:
                    err = JsonRpcError(id=req_id, error={"code": -32601, "message": "not found"})
                    writer.write((err.model_dump_json() + "\n").encode())
                    await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            writer.close()

    return await asyncio.start_server(default_handler, "127.0.0.1", port)


@pytest.mark.asyncio
async def test_send_command_success(free_port: int) -> None:
    server = await _start_server(free_port)
    client = SocketClient("127.0.0.1", free_port)
    await client.connect()

    loop_task = asyncio.create_task(client.run_event_loop())
    result = await client.send_command("event.subscribe", {"topics": ["run.*"]})
    assert result["subscription_id"] == "sub-abc"

    loop_task.cancel()
    try:
        await loop_task
    except asyncio.CancelledError:
        pass
    await client.close()
    server.close()
    await server.wait_closed()


@pytest.mark.asyncio
async def test_event_callback(free_port: int) -> None:
    server = await _start_server(free_port)
    client = SocketClient("127.0.0.1", free_port)
    await client.connect()

    events: list[dict[str, Any]] = []

    async def on_event(event: dict[str, Any]) -> None:
        events.append(event)

    client.on_event(on_event)
    loop_task = asyncio.create_task(client.run_event_loop())

    await client.send_command("agent.run", {"goal": "test"})
    await asyncio.sleep(0.2)

    assert len(events) == 2
    assert events[0]["type"] == "run.started"
    assert events[1]["type"] == "run.finished"

    loop_task.cancel()
    try:
        await loop_task
    except asyncio.CancelledError:
        pass
    await client.close()
    server.close()
    await server.wait_closed()


@pytest.mark.asyncio
async def test_ipc_error(free_port: int) -> None:
    async def error_handler(msg: dict[str, Any], writer: asyncio.StreamWriter) -> None:
        req_id = msg.get("id")
        err = JsonRpcError(id=req_id, error={"code": -32000, "message": "boom"})
        writer.write((err.model_dump_json() + "\n").encode())
        await writer.drain()

    server = await _start_server(free_port, error_handler)
    client = SocketClient("127.0.0.1", free_port)
    await client.connect()

    loop_task = asyncio.create_task(client.run_event_loop())
    with pytest.raises(IpcError) as exc_info:
        await client.send_command("agent.run", {"goal": "test"})
    assert exc_info.value.code == -32000
    assert "boom" in exc_info.value.message

    loop_task.cancel()
    try:
        await loop_task
    except asyncio.CancelledError:
        pass
    await client.close()
    server.close()
    await server.wait_closed()


@pytest.mark.asyncio
async def test_disconnect_cancels_pending(free_port: int) -> None:
    async def slow_handler(msg: dict[str, Any], writer: asyncio.StreamWriter) -> None:
        # Never respond
        await asyncio.sleep(10)

    server = await _start_server(free_port, slow_handler)
    client = SocketClient("127.0.0.1", free_port)
    await client.connect()

    task = asyncio.create_task(client.send_command("agent.run", {"goal": "test"}))
    await asyncio.sleep(0.1)

    # Close connection while pending
    await client.close()

    with pytest.raises(asyncio.CancelledError):
        await task

    server.close()
    await server.wait_closed()
