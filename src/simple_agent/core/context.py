from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecutionContext:
    run_id: str
    goal: str
    max_steps: int
    messages: list[dict[str, Any]] = field(default_factory=list)
    step: int = 0
    status: str = "running"  # "running" | "success" | "failed"
    reason: str | None = None
    prefill_messages: list[dict[str, Any]] | None = None
    session_notes: str = ""

    def __post_init__(self) -> None:
        if self.prefill_messages is not None:
            self.messages = list(self.prefill_messages)
        elif not self.messages:
            self.messages.append({"role": "user", "content": self.goal})

    def is_done(self) -> bool:
        return self.status in ("success", "failed")

    def mark_success(self) -> None:
        self.status = "success"

    def mark_failed(self, reason: str) -> None:
        self.status = "failed"
        self.reason = reason

    def add_assistant_message(
        self, content: str, tool_calls: list[dict[str, Any]] | None = None
    ) -> None:
        msg: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self.messages.append(msg)

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        self.messages.append(
            {"role": "tool", "tool_call_id": tool_call_id, "content": content}
        )

    def system_prompt(self, base: str) -> str:
        if not self.session_notes.strip():
            return base
        return (
            base
            + "\n\n## Session Notes\n"
            + self.session_notes.strip()
            + "\n\nRemember important durable facts by calling note_save."
        )
