from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from simple_agent.core.events.types import RunStartedEvent, StepStartedEvent
from simple_agent.core.transport.ipc_broadcaster import IpcEventBroadcaster


def _get_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def free_port() -> int:
    return _get_free_port()


async def _start_dummy_server(port: int) -> asyncio.Server:
    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        # Echo server: write back anything received so client reader can see it
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            writer.close()

    return await asyncio.start_server(handler, "127.0.0.1", port)


async def _read_event(reader: asyncio.StreamReader) -> dict[str, Any] | None:
    line = await asyncio.wait_for(reader.readline(), timeout=2.0)
    if not line:
        return None
    msg = json.loads(line)
    if msg.get("kind") == "event":
        return msg.get("event")
    return None


@pytest.mark.asyncio
async def test_topic_filter_match(free_port: int) -> None:
    server = await _start_dummy_server(free_port)
    broadcaster = IpcEventBroadcaster()

    reader1, writer1 = await asyncio.open_connection("127.0.0.1", free_port)
    broadcaster.subscribe(writer1, ["run.*"], "global")

    await broadcaster.handle(RunStartedEvent(run_id="r1", goal="g", ts="t"))
    event = await _read_event(reader1)
    assert event is not None
    assert event["type"] == "run.started"

    writer1.close()
    await writer1.wait_closed()
    server.close()
    await server.wait_closed()


@pytest.mark.asyncio
async def test_topic_filter_no_match(free_port: int) -> None:
    server = await _start_dummy_server(free_port)
    broadcaster = IpcEventBroadcaster()

    reader1, writer1 = await asyncio.open_connection("127.0.0.1", free_port)
    broadcaster.subscribe(writer1, ["run.*"], "global")

    await broadcaster.handle(StepStartedEvent(run_id="r1", step=1, ts="t"))
    await asyncio.sleep(0.05)
    assert reader1._buffer == b""

    writer1.close()
    await writer1.wait_closed()
    server.close()
    await server.wait_closed()


@pytest.mark.asyncio
async def test_scope_filter_global(free_port: int) -> None:
    server = await _start_dummy_server(free_port)
    broadcaster = IpcEventBroadcaster()

    reader1, writer1 = await asyncio.open_connection("127.0.0.1", free_port)
    broadcaster.subscribe(writer1, ["run.*"], "global")

    await broadcaster.handle(RunStartedEvent(run_id="r1", goal="g", ts="t"))
    event = await _read_event(reader1)
    assert event is not None

    writer1.close()
    await writer1.wait_closed()
    server.close()
    await server.wait_closed()


@pytest.mark.asyncio
async def test_scope_filter_run_specific(free_port: int) -> None:
    server = await _start_dummy_server(free_port)
    broadcaster = IpcEventBroadcaster()

    reader1, writer1 = await asyncio.open_connection("127.0.0.1", free_port)
    broadcaster.subscribe(writer1, ["run.*"], "run:r1")

    await broadcaster.handle(RunStartedEvent(run_id="r1", goal="g", ts="t"))
    event = await _read_event(reader1)
    assert event is not None

    writer1.close()
    await writer1.wait_closed()
    server.close()
    await server.wait_closed()


@pytest.mark.asyncio
async def test_scope_filter_run_specific_mismatch(free_port: int) -> None:
    server = await _start_dummy_server(free_port)
    broadcaster = IpcEventBroadcaster()

    reader1, writer1 = await asyncio.open_connection("127.0.0.1", free_port)
    broadcaster.subscribe(writer1, ["run.*"], "run:r2")

    await broadcaster.handle(RunStartedEvent(run_id="r1", goal="g", ts="t"))
    await asyncio.sleep(0.05)
    assert reader1._buffer == b""

    writer1.close()
    await writer1.wait_closed()
    server.close()
    await server.wait_closed()


@pytest.mark.asyncio
async def test_unsubscribe(free_port: int) -> None:
    server = await _start_dummy_server(free_port)
    broadcaster = IpcEventBroadcaster()

    reader1, writer1 = await asyncio.open_connection("127.0.0.1", free_port)
    broadcaster.subscribe(writer1, ["run.*"], "global")
    broadcaster.unsubscribe(writer1)

    await broadcaster.handle(RunStartedEvent(run_id="r1", goal="g", ts="t"))
    await asyncio.sleep(0.05)
    assert reader1._buffer == b""

    writer1.close()
    await writer1.wait_closed()
    server.close()
    await server.wait_closed()


@pytest.mark.asyncio
async def test_dead_writer_cleanup(free_port: int) -> None:
    server = await _start_dummy_server(free_port)
    broadcaster = IpcEventBroadcaster()

    reader1, writer1 = await asyncio.open_connection("127.0.0.1", free_port)
    broadcaster.subscribe(writer1, ["run.*"], "global")

    # Close writer to simulate dead connection
    writer1.close()
    await writer1.wait_closed()

    # Should not raise; dead writer should be cleaned up
    await broadcaster.handle(RunStartedEvent(run_id="r1", goal="g", ts="t"))
    assert len(broadcaster._subscriptions) == 0

    server.close()
    await server.wait_closed()
