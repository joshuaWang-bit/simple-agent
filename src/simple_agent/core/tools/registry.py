from __future__ import annotations

from typing import Any

from simple_agent.core.tools.base import BaseTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def tool_schemas(self) -> list[dict[str, Any]]:
        return [t.schema for t in self._tools.values()]

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)
