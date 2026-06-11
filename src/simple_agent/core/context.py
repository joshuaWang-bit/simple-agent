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
    transcript_messages: list[dict[str, Any]] = field(default_factory=list)
    global_context: str = ""
    project_context: str = ""
    session_notes: str = ""
    system_prompt_override: str | None = None
    result: str = ""

    def __post_init__(self) -> None:
        if self.prefill_messages is not None:
            self.messages = list(self.prefill_messages)
        elif not self.messages:
            self.messages.append({"role": "user", "content": self.goal})
        if not self.transcript_messages:
            self.transcript_messages = list(self.messages)

    def is_done(self) -> bool:
        return self.status in ("success", "failed")

    def mark_success(self, result: str | None = None) -> None:
        self.status = "success"
        if result is not None:
            self.result = result

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
        self.transcript_messages.append(msg)

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        msg = {"role": "tool", "tool_call_id": tool_call_id, "content": content}
        self.messages.append(msg)
        self.transcript_messages.append(msg)

    def system_prompt(self, base: str) -> str:
        parts = [self.system_prompt_override if self.system_prompt_override else base]
        if self.global_context.strip():
            parts.append("\n\n## Global Context\n" + self.global_context.strip())
        if self.project_context.strip():
            parts.append("\n\n## Project Context\n" + self.project_context.strip())
        if self.session_notes.strip():
            parts.append("\n\n## Session Notes\n" + self.session_notes.strip())
            parts.append("\n\nRemember important durable facts by calling note_save.")
        return "".join(parts)
