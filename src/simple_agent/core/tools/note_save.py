from __future__ import annotations

from typing import Any

from simple_agent.core.tools.base import BaseTool, ToolResult


class NoteSaveTool(BaseTool):
    def __init__(self, store: Any, session_id: str, run_id: str) -> None:
        self._store = store
        self._sid = session_id
        self._run_id = run_id

    @property
    def name(self) -> str:
        return "note_save"

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": (
                "Save a fact or decision to the session's notes. "
                "These notes will be visible to you in future turns of this session."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                },
                "required": ["content"],
            },
        }

    async def run(self, input: dict[str, Any]) -> ToolResult:
        content = str(input.get("content", "")).strip()
        if not content:
            return ToolResult(content="empty content", is_error=True)
        self._store.append_note(self._sid, content, self._run_id)
        return ToolResult(content="saved")
