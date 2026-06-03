from __future__ import annotations

from pathlib import Path
from typing import Any

from simple_agent.core.tools.base import BaseTool, ToolResult


class ReadFileTool(BaseTool):
    @property
    def name(self) -> str:
        return "read_file"

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": "Read the contents of a file.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"}
                },
                "required": ["path"],
            },
        }

    async def run(self, input: dict[str, Any]) -> ToolResult:
        path = Path(input["path"])
        try:
            return ToolResult(content=path.read_text(encoding="utf-8"))
        except Exception as e:
            return ToolResult(content=str(e), is_error=True)
