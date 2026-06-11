from __future__ import annotations

import asyncio
import sys
from typing import Any

from simple_agent.core.config import AgentConfig
from simple_agent.core.transport.socket_client import SocketClient


class ChatPrinter:
    def handle(self, event: dict[str, Any]) -> None:
        t = event.get("type", "")
        if t == "llm.token":
            print(event.get("token", ""), end="", flush=True)
        elif t == "tool.call_started":
            print(
                f"\n[tool] {event.get('tool_name', '')} {event.get('input', {})}"
            )
        elif t == "tool.call_finished":
            print(f"[tool] {event.get('tool_name', '')} done")
        elif t == "session.waiting_for_input":
            print("\n[waiting for input]")
        elif t == "llm.usage":
            pct = float(event.get("context_pct") or 0.0)
            print(
                "\n[tokens] "
                f"in={event.get('input_tokens')} "
                f"out={event.get('output_tokens')} "
                f"cache={event.get('cache_read_input_tokens')} "
                f"context={pct * 100:.1f}%"
            )
        elif t == "context.compacted":
            print(
                "\n[context compacted] "
                f"original={event.get('original_tokens')} "
                f"summary={event.get('summary_tokens')}"
            )
        elif t == "run.finished":
            print()


def cmd_chat(config: AgentConfig) -> None:
    try:
        asyncio.run(_chat_async(config))
    except KeyboardInterrupt:
        sys.exit(130)


async def _readline(prompt: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, input, prompt)


async def _chat_async(config: AgentConfig) -> int:
    client = SocketClient(config.host, config.port)
    try:
        await client.connect()
    except (ConnectionRefusedError, OSError):
        print(
            f"error: core not running ({config.host}:{config.port})",
            file=sys.stderr,
        )
        return 1

    printer = ChatPrinter()
    async def on_event(event: dict[str, Any]) -> None:
        printer.handle(event)

    client.on_event(on_event)
    loop_task = asyncio.create_task(client.run_event_loop())

    await client.send_command("event.subscribe", {
        "topics": ["session.*", "run.*", "step.*", "tool.*", "llm.*", "context.*"],
        "scope": "global",
    })
    created = await client.send_command("session.create", {"mode": "chat"})
    session_id = str(created["session_id"])
    print(f"[session: {session_id}]")

    try:
        while True:
            line = await _readline("> ")
            if not line.strip():
                continue
            if line.strip().startswith("/compact"):
                focus = line.strip().removeprefix("/compact").strip()
                await client.send_command("session.compact", {
                    "session_id": session_id,
                    "focus": focus,
                })
                continue
            await client.send_command("session.send_message", {
                "session_id": session_id,
                "content": line,
            })
    except EOFError:
        pass
    finally:
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass
        await client.close()
    return 0
