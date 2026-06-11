from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from simple_agent.core.session import Session
from simple_agent.core.session.truncate import (
    TOOL_RESULT_KEEP,
    TOOL_RESULT_LIMIT,
    truncate_tool_results,
)

logger = logging.getLogger(__name__)


class SessionStore:
    def __init__(
        self,
        base_dir: Path | None = None,
        *,
        tool_result_limit: int = TOOL_RESULT_LIMIT,
        tool_result_keep: int = TOOL_RESULT_KEEP,
    ) -> None:
        self._base = (base_dir or Path.home() / ".sagent" / "sessions").expanduser()
        self._tool_result_limit = tool_result_limit
        self._tool_result_keep = tool_result_keep
        self._base.mkdir(parents=True, exist_ok=True)

    def session_dir(self, sid: str) -> Path:
        return self._base / sid

    def runs_dir(self, sid: str) -> Path:
        return self.session_dir(sid) / "runs"

    def write_meta(self, session: Session) -> None:
        path = self.session_dir(session.id) / "meta.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "id": session.id,
                    "mode": session.mode,
                    "status": session.status,
                    "title": session.title,
                    "created_at": session.created_at,
                    "updated_at": session.updated_at,
                    "run_ids": session.run_ids,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def read_messages(self, sid: str) -> list[dict[str, Any]]:
        path = self.session_dir(sid) / "thread.jsonl"
        if not path.exists():
            return []

        messages: list[dict[str, Any]] = []
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("skip broken thread row sid=%s line=%s", sid, line_no)
                continue
            messages.append(msg)

        messages = self._trim_orphan_tool_calls(messages)
        return truncate_tool_results(
            messages,
            limit=self._tool_result_limit,
            keep=self._tool_result_keep,
        )

    def append_message(self, sid: str, message: dict[str, Any]) -> None:
        path = self.session_dir(sid) / "thread.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(message, ensure_ascii=False) + "\n")

    def write_compacted(self, sid: str, messages: list[dict[str, Any]]) -> Path:
        path = self.session_dir(sid) / "thread.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            backup = path.with_name(f"thread_{_stamp()}.jsonl.bak")
            shutil.copy2(path, backup)
        lines = [json.dumps(msg, ensure_ascii=False) for msg in messages]
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return path

    def read_notes(self, sid: str) -> str:
        path = self.session_dir(sid) / "notes.md"
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def append_note(self, sid: str, content: str, run_id: str) -> None:
        path = self.session_dir(sid) / "notes.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timezone

        ts = datetime.now(timezone.utc).isoformat()
        line = f"\n- [{ts}] (run {run_id}) {content}\n"
        with path.open("a", encoding="utf-8") as f:
            f.write(line)

    @staticmethod
    def _trim_orphan_tool_calls(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove trailing assistant messages with tool_calls that lack matching tool results."""
        while messages:
            last = messages[-1]
            if last.get("role") == "assistant" and last.get("tool_calls"):
                needed = len(last["tool_calls"])
                # Count tool messages that come after this assistant message
                tool_count = 0
                for msg in messages[len(messages) - 1 + 1 :]:
                    if msg.get("role") == "tool":
                        tool_count += 1
                if tool_count < needed:
                    messages.pop()
                    continue
            break
        return messages


def _stamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
