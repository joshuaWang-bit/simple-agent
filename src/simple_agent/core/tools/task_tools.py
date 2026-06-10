from __future__ import annotations

from typing import Any

from simple_agent.core.task import TaskManager
from simple_agent.core.tools.base import BaseTool, ToolResult


class TaskCreateTool(BaseTool):
    def __init__(self, manager: TaskManager) -> None:
        self._manager = manager

    @property
    def name(self) -> str:
        return "task_create"

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": "Create a new task. Optionally specify task IDs in blocked_by to declare dependencies.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "subject": {
                        "type": "string",
                        "description": "Short title of the task",
                    },
                    "description": {
                        "type": "string",
                        "description": "Detailed description of what this task involves",
                    },
                    "blocked_by": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "List of task IDs that must be completed before this task can start",
                    },
                },
                "required": ["subject"],
            },
        }

    async def run(self, input: dict[str, Any]) -> ToolResult:
        task = self._manager.create(
            subject=input["subject"],
            description=input.get("description", ""),
            blocked_by=input.get("blocked_by"),
        )
        return ToolResult(content=f"Created task #{task.id}: {task.subject}")


class TaskUpdateTool(BaseTool):
    def __init__(self, manager: TaskManager) -> None:
        self._manager = manager

    @property
    def name(self) -> str:
        return "task_update"

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": "Update a task's status or dependencies.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "integer",
                        "description": "ID of the task to update",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed"],
                        "description": "New status for the task",
                    },
                    "add_blocked_by": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Task IDs to add as blockers",
                    },
                    "remove_blocked_by": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Task IDs to remove from blockers",
                    },
                },
                "required": ["task_id"],
            },
        }

    async def run(self, input: dict[str, Any]) -> ToolResult:
        task_id = int(input["task_id"])
        task = self._manager.update(
            task_id=task_id,
            status=input.get("status"),
            add_blocked_by=input.get("add_blocked_by"),
            remove_blocked_by=input.get("remove_blocked_by"),
        )
        return ToolResult(content=f"Updated task #{task.id}: status={task.status}")


class TaskListTool(BaseTool):
    def __init__(self, manager: TaskManager) -> None:
        self._manager = manager

    @property
    def name(self) -> str:
        return "task_list"

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": "List all tasks with their current status in a compact format.",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        }

    async def run(self, input: dict[str, Any]) -> ToolResult:
        tasks = self._manager.list()
        if not tasks:
            return ToolResult(content="No tasks.")

        lines: list[str] = []
        for t in tasks:
            mark = {
                "pending": "[ ]",
                "in_progress": "[>]",
                "completed": "[x]",
            }.get(t.status, "[?]")
            line = f"{mark} #{t.id}: {t.subject}"
            if t.blocked_by:
                line += f" (blocked by: {t.blocked_by})"
            lines.append(line)
        return ToolResult(content="\n".join(lines))


class TaskGetTool(BaseTool):
    def __init__(self, manager: TaskManager) -> None:
        self._manager = manager

    @property
    def name(self) -> str:
        return "task_get"

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": "Get the full JSON representation of a single task.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "integer",
                        "description": "ID of the task",
                    },
                },
                "required": ["task_id"],
            },
        }

    async def run(self, input: dict[str, Any]) -> ToolResult:
        task_id = int(input["task_id"])
        task = self._manager.get(task_id)
        if task is None:
            return ToolResult(content=f"Task #{task_id} not found.", is_error=True)
        import json

        return ToolResult(content=json.dumps(task.to_dict(), indent=2, ensure_ascii=False))
