from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import json


@dataclass
class Task:
    id: int
    subject: str
    description: str = ""
    status: str = "pending"  # pending | in_progress | completed
    blocked_by: list[int] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "description": self.description,
            "status": self.status,
            "blocked_by": self.blocked_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Task:
        return cls(
            id=int(data["id"]),
            subject=data["subject"],
            description=data.get("description", ""),
            status=data.get("status", "pending"),
            blocked_by=[int(x) for x in data.get("blocked_by", [])],
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskManager:
    def __init__(self, tasks_dir: Path) -> None:
        self._dir = tasks_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._next_id = self._max_id() + 1

    def _max_id(self) -> int:
        max_id = 0
        for f in self._dir.glob("task_*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                max_id = max(max_id, int(data.get("id", 0)))
            except Exception:
                pass
        return max_id

    def create(
        self,
        subject: str,
        description: str = "",
        blocked_by: list[int] | None = None,
    ) -> Task:
        now = _now()
        task = Task(
            id=self._next_id,
            subject=subject,
            description=description,
            status="pending",
            blocked_by=list(blocked_by or []),
            created_at=now,
            updated_at=now,
        )
        self._save(task)
        self._next_id += 1
        return task

    def update(
        self,
        task_id: int,
        *,
        status: str | None = None,
        add_blocked_by: list[int] | None = None,
        remove_blocked_by: list[int] | None = None,
    ) -> Task:
        task = self._load(task_id)
        if status is not None:
            task.status = status
        if add_blocked_by:
            for dep in add_blocked_by:
                if dep not in task.blocked_by:
                    task.blocked_by.append(dep)
        if remove_blocked_by:
            task.blocked_by = [x for x in task.blocked_by if x not in remove_blocked_by]
        if status == "completed":
            self._clear_dependency(task_id)
        task.updated_at = _now()
        self._save(task)
        return task

    def get(self, task_id: int) -> Task | None:
        try:
            return self._load(task_id)
        except FileNotFoundError:
            return None

    def list(self) -> list[Task]:
        tasks: list[Task] = []
        for f in sorted(self._dir.glob("task_*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                tasks.append(Task.from_dict(data))
            except Exception:
                pass
        return tasks

    def _task_path(self, task_id: int) -> Path:
        return self._dir / f"task_{task_id}.json"

    def _save(self, task: Task) -> None:
        path = self._task_path(task.id)
        path.write_text(
            json.dumps(task.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _load(self, task_id: int) -> Task:
        path = self._task_path(task_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        return Task.from_dict(data)

    def _clear_dependency(self, completed_id: int) -> None:
        for f in self._dir.glob("task_*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                blocked = [int(x) for x in data.get("blocked_by", [])]
                if completed_id in blocked:
                    data["blocked_by"] = [x for x in blocked if x != completed_id]
                    data["updated_at"] = _now()
                    f.write_text(
                        json.dumps(data, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
            except Exception:
                pass
