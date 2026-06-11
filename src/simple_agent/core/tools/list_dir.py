from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from simple_agent.core.tools.base import BaseTool, ToolResult


class ListDirParams(BaseModel):
    model_config = ConfigDict(extra="ignore")
    path: str
    max_depth: int = 1


class ListDirTool(BaseTool):
    params_model = ListDirParams

    @property
    def name(self) -> str:
        return "list_dir"

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": "List directory contents. Optionally control recursion depth.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path to list",
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum recursion depth (0 = only the given directory)",
                    },
                },
                "required": ["path"],
            },
        }

    async def run(self, input: dict[str, Any]) -> ToolResult:
        raw_path = input["path"]
        max_depth = input.get("max_depth", 1)
        if ".." in raw_path:
            return ToolResult(content="Path traversal not allowed.", is_error=True)

        root = Path(raw_path)
        if not root.exists():
            return ToolResult(content=f"Directory not found: {root}", is_error=True)
        if not root.is_dir():
            return ToolResult(content=f"Not a directory: {root}", is_error=True)

        lines: list[str] = []
        self._list(root, max_depth, 0, lines)
        return ToolResult(content="\n".join(lines) or "(empty directory)")

    def _list(self, path: Path, max_depth: int, current_depth: int, lines: list[str]) -> None:
        if current_depth > max_depth:
            return
        prefix = "  " * current_depth
        try:
            entries = sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            lines.append(f"{prefix}[permission denied]")
            return

        for entry in entries:
            name = entry.name
            if entry.is_dir():
                lines.append(f"{prefix}{name}/")
                self._list(entry, max_depth, current_depth + 1, lines)
            else:
                lines.append(f"{prefix}{name}")
