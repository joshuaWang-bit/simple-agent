from __future__ import annotations

import time
from typing import Any

from simple_agent.core.events.bus import EventBus
from simple_agent.core.events.types import ToolCallFinishedEvent, ToolCallStartedEvent
from simple_agent.core.tools.base import ToolResult
from simple_agent.core.tools.registry import ToolRegistry


class ToolCall:
    def __init__(self, id: str, name: str, input: dict[str, Any]) -> None:
        self.id = id
        self.name = name
        self.input = input


async def invoke_tool(
    registry: ToolRegistry,
    tc: ToolCall,
    bus: EventBus,
    run_id: str,
) -> ToolResult:
    tool = registry.get(tc.name)
    if not tool:
        return ToolResult(content=f"Unknown tool: {tc.name}", is_error=True)

    await bus.publish(
        ToolCallStartedEvent(
            run_id=run_id,
            tool_use_id=tc.id,
            tool_name=tc.name,
            input=tc.input,
            ts=_now(),
        )
    )
    t0 = time.perf_counter()
    try:
        result = await tool.run(tc.input)
    except Exception as e:
        result = ToolResult(content=str(e), is_error=True)
    elapsed = int((time.perf_counter() - t0) * 1000)

    await bus.publish(
        ToolCallFinishedEvent(
            run_id=run_id,
            tool_use_id=tc.id,
            tool_name=tc.name,
            elapsed_ms=elapsed,
            output=result.content,
            ts=_now(),
        )
    )
    return result


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
