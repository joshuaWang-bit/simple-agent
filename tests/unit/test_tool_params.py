from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, Field

from simple_agent.core.events.bus import EventBus
from simple_agent.core.tools.base import BaseTool, ToolResult
from simple_agent.core.tools.invoke import ToolCall, invoke_tool
from simple_agent.core.tools.registry import ToolRegistry


class StrictParams(BaseModel):
    model_config = ConfigDict(extra="ignore")
    value: int = Field(ge=0)


class StrictTool(BaseTool):
    params_model = StrictParams

    @property
    def name(self) -> str:
        return "strict_tool"

    @property
    def schema(self) -> dict[str, Any]:
        return {"name": self.name, "input_schema": {"type": "object"}}

    async def run(self, input: dict[str, Any]) -> ToolResult:
        return ToolResult(content=f"got {input['value']}")


class NoParamsTool(BaseTool):
    params_model = None

    @property
    def name(self) -> str:
        return "no_params_tool"

    @property
    def schema(self) -> dict[str, Any]:
        return {"name": self.name, "input_schema": {"type": "object"}}

    async def run(self, input: dict[str, Any]) -> ToolResult:
        return ToolResult(content="ok")


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.mark.asyncio
async def test_params_validation_fails_schema_error(bus: EventBus) -> None:
    tool = StrictTool()
    registry = ToolRegistry()
    registry.register(tool)
    tc = ToolCall("id1", "strict_tool", {"value": -1})

    result = await invoke_tool(registry, tc, bus, "run1")
    assert result.is_error is True
    assert "schema_error" in result.content


@pytest.mark.asyncio
async def test_params_validation_passes(bus: EventBus) -> None:
    tool = StrictTool()
    registry = ToolRegistry()
    registry.register(tool)
    tc = ToolCall("id1", "strict_tool", {"value": 5})

    result = await invoke_tool(registry, tc, bus, "run1")
    assert result.is_error is False
    assert "got 5" in result.content


@pytest.mark.asyncio
async def test_extra_fields_ignored(bus: EventBus) -> None:
    tool = StrictTool()
    registry = ToolRegistry()
    registry.register(tool)
    tc = ToolCall("id1", "strict_tool", {"value": 5, "extra_field": "hello"})

    result = await invoke_tool(registry, tc, bus, "run1")
    assert result.is_error is False
    assert "got 5" in result.content


@pytest.mark.asyncio
async def test_no_params_model_skips_validation(bus: EventBus) -> None:
    tool = NoParamsTool()
    registry = ToolRegistry()
    registry.register(tool)
    tc = ToolCall("id1", "no_params_tool", {"anything": "goes"})

    result = await invoke_tool(registry, tc, bus, "run1")
    assert result.is_error is False
    assert result.content == "ok"


@pytest.mark.asyncio
async def test_params_validation_fails_missing_required(bus: EventBus) -> None:
    tool = StrictTool()
    registry = ToolRegistry()
    registry.register(tool)
    tc = ToolCall("id1", "strict_tool", {})

    result = await invoke_tool(registry, tc, bus, "run1")
    assert result.is_error is True
    assert "schema_error" in result.content
