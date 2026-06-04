from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from simple_agent.core.llm.provider import LlmResponse
from simple_agent.core.transport.socket_client import SocketClient


class FakeProvider:
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        bus: Any,
        run_id: str,
        *,
        step: int = 0,
    ) -> LlmResponse:
        await asyncio.sleep(0.1)
        return LlmResponse(text="done", stop_reason="end_turn")


@pytest.fixture
def free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def running_daemon(free_port: int):
    daemon_path = Path(__file__).parent / "test_daemon.py"
    proc = subprocess.Popen(
        [sys.executable, str(daemon_path)],
        env={
            **os.environ,
            "SAGENT_PORT": str(free_port),
            "SAGENT_LOG_LEVEL": "WARNING",
        },
    )

    async def _probe() -> bool:
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            await asyncio.sleep(0.05)
            try:
                _, w = await asyncio.open_connection("127.0.0.1", free_port)
                w.close()
                return True
            except (ConnectionRefusedError, OSError):
                pass
        return False

    ready = asyncio.run(_probe())
    if not ready:
        proc.terminate()
        proc.wait(timeout=2)
        pytest.skip("daemon failed to start")

    yield proc
    proc.terminate()
    proc.wait(timeout=2)


@pytest.mark.asyncio
async def test_agent_run_emits_run_started(free_port: int, running_daemon: subprocess.Popen) -> None:
    client = SocketClient("127.0.0.1", free_port)
    await client.connect()

    events: list[dict[str, Any]] = []

    async def on_event(event: dict[str, Any]) -> None:
        events.append(event)

    client.on_event(on_event)
    loop_task = asyncio.create_task(client.run_event_loop())

    await client.send_command("event.subscribe", {
        "topics": ["run.*"],
        "scope": "global",
    })
    result = await client.send_command("agent.run", {"goal": "test goal"})
    run_id = result["run_id"]

    # Wait for run.started
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if any(e.get("type") == "run.started" for e in events):
            break
        await asyncio.sleep(0.1)
    else:
        raise TimeoutError("did not receive run.started")

    started_events = [e for e in events if e.get("type") == "run.started"]
    assert len(started_events) == 1
    assert started_events[0].get("run_id") == run_id

    loop_task.cancel()
    try:
        await loop_task
    except asyncio.CancelledError:
        pass
    await client.close()


@pytest.mark.asyncio
async def test_two_clients_receive_same_events(free_port: int, running_daemon: subprocess.Popen) -> None:
    client1 = SocketClient("127.0.0.1", free_port)
    client2 = SocketClient("127.0.0.1", free_port)
    await client1.connect()
    await client2.connect()

    event1 = asyncio.Event()
    event2 = asyncio.Event()

    async def on_event1(ev: dict[str, Any]) -> None:
        if ev.get("type") == "run.started":
            event1.set()

    async def on_event2(ev: dict[str, Any]) -> None:
        if ev.get("type") == "run.started":
            event2.set()

    client1.on_event(on_event1)
    client2.on_event(on_event2)
    loop1 = asyncio.create_task(client1.run_event_loop())
    loop2 = asyncio.create_task(client2.run_event_loop())

    await client1.send_command("event.subscribe", {"topics": ["run.*"], "scope": "global"})
    await client2.send_command("event.subscribe", {"topics": ["run.*"], "scope": "global"})
    await client1.send_command("agent.run", {"goal": "test"})

    await asyncio.wait_for(
        asyncio.gather(event1.wait(), event2.wait()),
        timeout=5.0,
    )

    for lt in (loop1, loop2):
        lt.cancel()
        try:
            await lt
        except asyncio.CancelledError:
            pass
    await client1.close()
    await client2.close()


@pytest.mark.asyncio
async def test_event_replay(free_port: int, running_daemon: subprocess.Popen) -> None:
    # Step 1: trigger a run and capture run_id
    client1 = SocketClient("127.0.0.1", free_port)
    await client1.connect()

    events: list[dict[str, Any]] = []

    async def on_event(ev: dict[str, Any]) -> None:
        events.append(ev)

    client1.on_event(on_event)
    loop1 = asyncio.create_task(client1.run_event_loop())

    await client1.send_command("event.subscribe", {"topics": ["run.*"], "scope": "global"})
    result = await client1.send_command("agent.run", {"goal": "replay test"})
    run_id = result["run_id"]

    # Wait for run.started
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if any(e.get("type") == "run.started" for e in events):
            break
        await asyncio.sleep(0.1)

    loop1.cancel()
    try:
        await loop1
    except asyncio.CancelledError:
        pass
    await client1.close()

    # Step 2: reconnect with replay
    client2 = SocketClient("127.0.0.1", free_port)
    await client2.connect()

    replay_events: list[dict[str, Any]] = []

    async def on_event2(ev: dict[str, Any]) -> None:
        replay_events.append(ev)

    client2.on_event(on_event2)
    loop2 = asyncio.create_task(client2.run_event_loop())

    sub_result = await client2.send_command("event.subscribe", {
        "topics": ["run.*"],
        "scope": "global",
        "replay_from_run": run_id,
    })

    assert sub_result.get("replayed_count", 0) > 0

    # Should have received replayed events
    await asyncio.sleep(0.3)
    assert any(e.get("type") == "run.started" for e in replay_events)

    loop2.cancel()
    try:
        await loop2
    except asyncio.CancelledError:
        pass
    await client2.close()
