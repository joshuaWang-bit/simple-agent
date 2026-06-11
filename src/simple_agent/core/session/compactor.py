from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from simple_agent.core.context import ExecutionContext
from simple_agent.core.events.bus import EventBus
from simple_agent.core.events.types import ContextCompactedEvent


@dataclass
class CompactionResult:
    summary_text: str
    original_tokens: int
    summary_tokens: int


class SilentBus:
    async def publish(self, event: Any) -> None:
        return None


class Compactor:
    def __init__(self, bus: EventBus, output_dir: Path, session_id: str = "") -> None:
        self._bus = bus
        self._output_dir = output_dir
        self._session_id = session_id

    async def compact(self, context: ExecutionContext, provider: Any) -> bool:
        result = await self.compact_messages(context.messages, provider)
        if result is None:
            return False

        context.messages = summary_messages(result.summary_text)
        summary_path = self.write_summary(result.summary_text)
        await self._bus.publish(
            ContextCompactedEvent(
                run_id=context.run_id,
                session_id=self._session_id,
                original_tokens=result.original_tokens,
                summary_tokens=result.summary_tokens,
                summary_path=str(summary_path),
                persistent=False,
                ts=_now(),
            )
        )
        return True

    async def compact_messages(
        self,
        messages: list[dict[str, Any]],
        provider: Any,
        *,
        focus: str = "",
    ) -> CompactionResult | None:
        if not messages:
            return None

        prompt = _build_compaction_prompt(messages, focus=focus)
        compress_request = [{"role": "user", "content": prompt}]

        try:
            response = await provider.chat(
                messages=compress_request,
                tool_schemas=[],
                bus=SilentBus(),
                run_id="compact",
                step=0,
                system="You are a helpful assistant that summarizes conversations.",
            )
        except Exception:
            return None

        summary = str(getattr(response, "text", "") or "").strip()
        if not summary:
            return None

        original_tokens = estimate_tokens(messages)
        summary_tokens = estimate_tokens(summary)
        if summary_tokens >= original_tokens:
            return None

        return CompactionResult(
            summary_text=summary,
            original_tokens=original_tokens,
            summary_tokens=summary_tokens,
        )

    def write_summary(self, summary_text: str) -> Path:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        path = self._output_dir / f"summary_{_stamp()}.md"
        path.write_text(summary_text + "\n", encoding="utf-8")
        return path


def summary_messages(summary_text: str) -> list[dict[str, Any]]:
    return [
        {"role": "user", "content": summary_text},
        {"role": "assistant", "content": "Understood, I'll continue from this summary."},
    ]


def _build_compaction_prompt(messages: list[dict[str, Any]], *, focus: str = "") -> str:
    serialized = json.dumps(messages, ensure_ascii=False, indent=2)
    focus_text = focus.strip()
    focus_section = f"\n\nUser focus for this compaction:\n{focus_text}\n" if focus_text else ""
    return (
        "Compress the conversation below into a handoff summary for an agent that "
        "must continue the same task without seeing the original history.\n"
        "Use exactly these sections:\n\n"
        "## 1. Original Goal\n"
        "## 2. Completed Steps\n"
        "## 3. Key Constraints & Discoveries\n"
        "## 4. Current File State\n"
        "## 5. Remaining TODOs\n"
        "## 6. Critical Data\n\n"
        "Preserve exact file paths, identifiers, errors, commands, and user constraints. "
        "Do not invent facts. Do not call tools."
        f"{focus_section}\n\nConversation JSON:\n{serialized}"
    )


def estimate_tokens(value: Any) -> int:
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False)
    return max(1, (len(value) + 3) // 4)


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
