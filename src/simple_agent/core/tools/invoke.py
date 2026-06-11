from __future__ import annotations

import asyncio
import time
from typing import Any

from pydantic import ValidationError

from simple_agent.core.events.bus import EventBus
from simple_agent.core.events.types import (
    PermissionRequestedEvent,
    ToolCallFailedEvent,
    ToolCallFinishedEvent,
    ToolCallStartedEvent,
)
from simple_agent.core.permissions import PermissionManager
from simple_agent.core.tools.base import ToolResult
from simple_agent.core.tools.registry import ToolRegistry


class RateLimitedError(Exception):
    """Raised when a tool invocation is rate-limited by an upstream service."""
    pass


class ToolCall:
    def __init__(self, id: str, name: str, input: dict[str, Any]) -> None:
        self.id = id
        self.name = name
        self.input = input


_MAX_RETRIES = 2
_RETRY_BASE_S = 2.0
_RETRYABLE = {"runtime_error", "rate_limited"}


async def invoke_tool(
    registry: ToolRegistry,
    tc: ToolCall,
    bus: EventBus,
    run_id: str,
    permission_manager: PermissionManager | None = None,
    session_id: str | None = None,
) -> ToolResult:
    tool = registry.get(tc.name)
    if not tool:
        return ToolResult(content=f"Unknown tool: {tc.name}", is_error=True)

    # 1. pydantic validation
    if tool.params_model is not None:
        try:
            tool.params_model.model_validate(dict(tc.input))
        except ValidationError as exc:
            return await _fail(
                bus, run_id, tc, "schema_error", str(exc), elapsed_ms=0
            )

    # 2. permission check
    if permission_manager is not None and session_id is not None:
        async def _emit_permission(raw: dict[str, Any]) -> None:
            await bus.publish(PermissionRequestedEvent(**raw, run_id=run_id))

        allowed, decision = await permission_manager.check_and_wait(
            tool_use_id=tc.id,
            tool_name=tc.name,
            params=dict(tc.input),
            session_id=session_id,
            event_emitter=_emit_permission,
        )
        if not allowed:
            return await _fail(
                bus, run_id, tc, "permission_denied",
                f"Permission denied ({decision})", elapsed_ms=0,
            )

    # 3. publish started event
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
    timeout = 120

    # 4. execute with retry
    for attempt in range(1, _MAX_RETRIES + 2):
        try:
            result = await asyncio.wait_for(
                tool.run(dict(tc.input)), timeout=timeout
            )
            if result.is_error:
                error_class = result.error_type or "runtime_error"
                error_message = result.content
            else:
                elapsed = int((time.perf_counter() - t0) * 1000)
                await bus.publish(
                    ToolCallFinishedEvent(
                        run_id=run_id,
                        tool_use_id=tc.id,
                        tool_name=tc.name,
                        elapsed_ms=elapsed,
                        output=result.content,
                        is_error=False,
                        ts=_now(),
                    )
                )
                return result
        except TimeoutError:
            elapsed = int((time.perf_counter() - t0) * 1000)
            return await _fail(
                bus, run_id, tc, "timeout",
                f"timeout after {timeout}s", elapsed_ms=elapsed,
            )
        except RateLimitedError as exc:
            error_class = "rate_limited"
            error_message = str(exc)
        except Exception as exc:
            error_class = "runtime_error"
            error_message = str(exc)

        if error_class in _RETRYABLE and attempt <= _MAX_RETRIES:
            elapsed = int((time.perf_counter() - t0) * 1000)
            await bus.publish(
                ToolCallFailedEvent(
                    run_id=run_id,
                    tool_use_id=tc.id,
                    tool_name=tc.name,
                    error_class=error_class,
                    error_message=error_message,
                    attempt=attempt,
                    ts=_now(),
                )
            )
            await asyncio.sleep(_RETRY_BASE_S * (2 ** (attempt - 1)))
            continue

        elapsed = int((time.perf_counter() - t0) * 1000)
        return await _fail(
            bus, run_id, tc, error_class, error_message,
            elapsed_ms=elapsed, attempt=attempt,
        )

    # unreachable
    elapsed = int((time.perf_counter() - t0) * 1000)
    return await _fail(
        bus, run_id, tc, "runtime_error", "unexpected fallthrough",
        elapsed_ms=elapsed,
    )


async def _fail(
    bus: EventBus,
    run_id: str,
    tc: ToolCall,
    error_class: str,
    error_message: str,
    elapsed_ms: int,
    attempt: int | None = None,
) -> ToolResult:
    await bus.publish(
        ToolCallFailedEvent(
            run_id=run_id,
            tool_use_id=tc.id,
            tool_name=tc.name,
            error_class=error_class,
            error_message=error_message,
            attempt=attempt,
            ts=_now(),
        )
    )
    await bus.publish(
        ToolCallFinishedEvent(
            run_id=run_id,
            tool_use_id=tc.id,
            tool_name=tc.name,
            elapsed_ms=elapsed_ms,
            output=f"[{error_class}] {error_message}",
            is_error=True,
            ts=_now(),
        )
    )
    return ToolResult(
        content=f"[{error_class}] {error_message}",
        is_error=True,
        error_type=error_class,
    )


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
