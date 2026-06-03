from __future__ import annotations

import asyncio
import sys
from typing import Any

from simple_agent.core.config import AgentConfig
from simple_agent.core.printer import StdoutPrinter
from simple_agent.core.transport.socket_client import SocketClient


def cmd_run(goal: str, config: AgentConfig) -> None:
    try:
        asyncio.run(_run_async(goal, config))
    except KeyboardInterrupt:
        sys.exit(130)


async def _run_async(goal: str, config: AgentConfig) -> int:
    client = SocketClient(config.host, config.port)
    try:
        await client.connect()
    except (ConnectionRefusedError, OSError):
        print(
            f"error: core not running ({config.host}:{config.port})",
            file=sys.stderr,
        )
        return 1

    printer = StdoutPrinter()
    finished = asyncio.Event()
    exit_code = 0

    async def on_event(event: dict[str, Any]) -> None:
        nonlocal exit_code
        await printer.handle(event)
        if event.get("type") == "run.finished":
            exit_code = 0 if event.get("status") == "success" else 1
            finished.set()

    client.on_event(on_event)
    loop_task = asyncio.create_task(client.run_event_loop())

    await client.send_command("event.subscribe", {
        "topics": ["run.*", "step.*", "tool.*", "llm.*"],
        "scope": "global",
    })
    await client.send_command("agent.run", {"goal": goal})
    await finished.wait()

    loop_task.cancel()
    try:
        await loop_task
    except asyncio.CancelledError:
        pass
    await client.close()
    return exit_code
