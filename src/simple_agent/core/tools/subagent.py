from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

from simple_agent.core.context import ExecutionContext
from simple_agent.core.tools.base import BaseTool, ToolResult


class SpawnAgentParams(BaseModel):
    model_config = ConfigDict(extra="ignore")

    description: str
    prompt: str
    run_in_background: bool = False
    subagent_type: str = ""


class AgentResultParams(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_id: str


@dataclass
class BackgroundSubagent:
    task: asyncio.Task[ExecutionContext]


class BackgroundSubagentRegistry:
    def __init__(self) -> None:
        self._items: dict[str, BackgroundSubagent] = {}

    def register(
        self,
        run_id: str,
        task: asyncio.Task[ExecutionContext],
    ) -> None:
        self._items[run_id] = BackgroundSubagent(task=task)

    def get(self, run_id: str) -> BackgroundSubagent | None:
        return self._items.get(run_id)


class SpawnAgentTool(BaseTool):
    params_model = SpawnAgentParams

    def __init__(
        self,
        spawn: Callable[[SpawnAgentParams], Awaitable[ToolResult]],
    ) -> None:
        self._spawn = spawn

    @property
    def name(self) -> str:
        return "spawn_agent"

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": "Spawn an isolated subagent with its own prompt, role, tools, and run id.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Short human-readable description of the subagent task",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Complete task prompt for the child agent",
                    },
                    "run_in_background": {
                        "type": "boolean",
                        "description": "If true, return immediately and retrieve the result with agent_result",
                    },
                    "subagent_type": {
                        "type": "string",
                        "description": "Optional role profile name, such as planner, executor, or reviewer",
                    },
                },
                "required": ["description", "prompt"],
            },
        }

    async def run(self, input: dict[str, Any]) -> ToolResult:
        params = SpawnAgentParams.model_validate(input)
        return await self._spawn(params)


class AgentResultTool(BaseTool):
    params_model = AgentResultParams

    def __init__(self, registry: BackgroundSubagentRegistry) -> None:
        self._registry = registry

    @property
    def name(self) -> str:
        return "agent_result"

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": "Check the result of a background subagent spawned earlier.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "run_id": {
                        "type": "string",
                        "description": "Child run id returned by spawn_agent",
                    }
                },
                "required": ["run_id"],
            },
        }

    async def run(self, input: dict[str, Any]) -> ToolResult:
        params = AgentResultParams.model_validate(input)
        item = self._registry.get(params.run_id)
        if item is None:
            return ToolResult(
                content=f"Unknown background subagent: {params.run_id}",
                is_error=True,
            )
        if not item.task.done():
            return ToolResult(content=f"Subagent still running: {params.run_id}")
        if item.task.cancelled():
            return ToolResult(
                content=f"Subagent was cancelled: {params.run_id}",
                is_error=True,
                error_type="runtime_error",
            )
        exc = item.task.exception()
        if exc is not None:
            return ToolResult(
                content=f"Subagent raised an exception: {exc}",
                is_error=True,
                error_type="runtime_error",
            )
        context = item.task.result()
        if context.status == "failed":
            return ToolResult(
                content=(
                    context.result
                    or context.reason
                    or "Subagent failed with no result."
                ),
                is_error=True,
                error_type="runtime_error",
            )
        return ToolResult(
            content=context.result or "Subagent completed with no text result."
        )
