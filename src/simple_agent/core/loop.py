from __future__ import annotations

import asyncio
import json
from typing import Any

from simple_agent.core.context import ExecutionContext
from simple_agent.core.events.bus import EventBus
from simple_agent.core.events.types import (
    LlmRequestEvent,
    LlmTokenEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StepFinishedEvent,
    StepStartedEvent,
    ToolCallFinishedEvent,
    ToolCallStartedEvent,
)
from simple_agent.core.llm.provider import OpenAICompatibleProvider, ToolCall
from simple_agent.core.permissions import PermissionManager
from simple_agent.core.session.compactor import Compactor
from simple_agent.core.tools.invoke import invoke_tool
from simple_agent.core.tools.registry import ToolRegistry


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


BASE_SYSTEM_PROMPT = (
    "You are an autonomous agent. When given a complex goal, "
    "break it down into sub-tasks using task_create. "
    "Set blocked_by dependencies when tasks must wait for others. "
    "Use task_update to mark tasks in_progress and completed. "
    "Use task_list to review progress. "
    "You have access to read_file, write_file, list_dir, and bash tools. "
    "Plan step by step, execute tools, and update task status accordingly."
)


class AgentLoop:
    def __init__(
        self,
        provider: OpenAICompatibleProvider,
        registry: ToolRegistry,
        bus: EventBus,
        permission_manager: PermissionManager | None = None,
        session_id: str | None = None,
        compactor: Compactor | None = None,
        compact_threshold: float = 0.0,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._bus = bus
        self._permission_manager = permission_manager
        self._session_id = session_id
        self._compactor = compactor
        self._compact_threshold = compact_threshold

    async def run(self, context: ExecutionContext) -> None:
        while not context.is_done():
            context.step += 1
            await self._bus.publish(
                StepStartedEvent(
                    run_id=context.run_id,
                    step=context.step,
                    ts=_now(),
                )
            )

            # — plan: 让 LLM 思考下一步 —
            try:
                response = await self._provider.chat(
                    messages=context.messages,
                    tool_schemas=self._registry.tool_schemas(),
                    bus=self._bus,
                    run_id=context.run_id,
                    step=context.step,
                    system=context.system_prompt(BASE_SYSTEM_PROMPT),
                )
            except asyncio.CancelledError:
                context.mark_failed("cancelled")
                raise
            except Exception as exc:
                import logging

                logger = logging.getLogger(__name__)
                logger.exception("LLM request failed: %s", exc)
                context.mark_failed(f"llm_error: {exc}")
                break

            # — observe: 把 LLM 响应追加到对话历史 —
            tool_calls: list[dict[str, Any]] | None = None
            if response.tool_calls:
                tool_calls = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.input),
                        },
                    }
                    for tc in response.tool_calls
                ]
            context.add_assistant_message(response.text or "", tool_calls)

            # — act: 如果 LLM 要求调用工具，执行它 —
            if response.stop_reason == "tool_use":
                for tc in response.tool_calls:
                    result = await invoke_tool(
                        self._registry,
                        tc,
                        self._bus,
                        context.run_id,
                        permission_manager=self._permission_manager,
                        session_id=self._session_id,
                    )
                    context.add_tool_result(tc.id, result.content)

                if (
                    not context.is_done()
                    and self._compactor is not None
                    and self._compact_threshold > 0
                    and response.usage is not None
                    and response.usage.context_pct >= self._compact_threshold
                ):
                    await self._compactor.compact(context, self._provider)

            # — 终止检查 —
            if response.stop_reason == "end_turn":
                context.mark_success(response.text or "")
            elif context.step >= context.max_steps:
                context.mark_failed("exceeded_max_steps")

            await self._bus.publish(
                StepFinishedEvent(
                    run_id=context.run_id,
                    step=context.step,
                    status=context.status,
                    ts=_now(),
                )
            )
