from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from simple_agent.core.tools.base import BaseTool, ToolResult


class WriteFileParams(BaseModel):
    model_config = ConfigDict(extra="ignore")
    path: str
    content: str


class WriteFileTool(BaseTool):
    params_model = WriteFileParams

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": "Write content to a file. Parent directories are created automatically. Path traversal is blocked.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path to write",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write",
                    },
                },
                "required": ["path", "content"],
            },
        }

    async def run(self, input: dict[str, Any]) -> ToolResult:
        raw_path = input["path"]
        # Basic path traversal guard
        if ".." in raw_path:
            return ToolResult(content="Path traversal not allowed.", is_error=True)

        path = Path(raw_path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(input["content"], encoding="utf-8")
            return ToolResult(content=f"Wrote {path}")
        except Exception as e:
            return ToolResult(content=str(e), is_error=True)
