from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from simple_agent.core.context import ExecutionContext
from simple_agent.core.events.bus import EventBus
from simple_agent.core.events.types import ContextCompactedEvent
from simple_agent.core.llm.provider import LlmResponse, LlmUsage, ToolCall
from simple_agent.core.loop import AgentLoop
from simple_agent.core.session.compactor import Compactor
from simple_agent.core.session.store import SessionStore
from simple_agent.core.session.truncate import truncate_tool_results
from simple_agent.core.tools import ReadFileTool, ToolRegistry


def test_truncate_tool_results_openai_message_is_immutable() -> None:
    original = [{"role": "tool", "tool_call_id": "tc1", "content": "x" * 20}]

    truncated = truncate_tool_results(original, limit=10, keep=4)

    assert original[0]["content"] == "x" * 20
    assert truncated[0]["content"].startswith("xxxx\n[... 16 chars omitted.")


def test_truncate_tool_results_anthropic_blocks_keeps_other_blocks() -> None:
    original = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "hello"},
                {"type": "tool_result", "content": "y" * 20},
            ],
        }
    ]

    truncated = truncate_tool_results(original, limit=10, keep=5)

    blocks = truncated[0]["content"]
    assert blocks[0] == {"type": "text", "text": "hello"}
    assert blocks[1]["content"].startswith("yyyyy\n[... 15 chars omitted.")


def test_session_store_truncates_on_read_without_changing_thread(tmp_path: Path) -> None:
    store = SessionStore(tmp_path, tool_result_limit=10, tool_result_keep=4)
    sid = "sess-test"
    store.append_message(sid, {"role": "tool", "tool_call_id": "tc1", "content": "z" * 20})

    messages = store.read_messages(sid)

    assert messages[0]["content"].startswith("zzzz\n[... 16 chars omitted.")
    raw = (tmp_path / sid / "thread.jsonl").read_text(encoding="utf-8")
    assert '"zzzzzzzzzzzzzzzzzzzz"' in raw


def test_session_store_write_compacted_keeps_backup(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sid = "sess-test"
    store.append_message(sid, {"role": "user", "content": "original"})

    store.write_compacted(sid, [{"role": "user", "content": "summary"}])

    thread = tmp_path / sid / "thread.jsonl"
    backups = list((tmp_path / sid).glob("thread_*.jsonl.bak"))
    assert json.loads(thread.read_text(encoding="utf-8").splitlines()[0])["content"] == "summary"
    assert len(backups) == 1
    assert "original" in backups[0].read_text(encoding="utf-8")


def test_execution_context_system_prompt_includes_three_context_layers() -> None:
    ctx = ExecutionContext(
        run_id="r1",
        goal="g",
        max_steps=1,
        global_context="global facts",
        project_context="project rules",
        session_notes="session facts",
    )

    prompt = ctx.system_prompt("base")

    assert "## Global Context\nglobal facts" in prompt
    assert "## Project Context\nproject rules" in prompt
    assert "## Session Notes\nsession facts" in prompt


class SummaryProvider:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[dict[str, Any]] = []

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        bus: EventBus,
        run_id: str,
        *,
        step: int = 0,
        system: str | None = None,
    ) -> LlmResponse:
        self.calls.append(
            {
                "messages": messages,
                "tool_schemas": tool_schemas,
                "run_id": run_id,
                "system": system,
            }
        )
        return LlmResponse(text=self.text, stop_reason="end_turn")


@pytest.mark.asyncio
async def test_compactor_replaces_memory_and_writes_summary(tmp_path: Path) -> None:
    events: list[ContextCompactedEvent] = []
    bus = EventBus()
    bus.subscribe(lambda event: events.append(event) if isinstance(event, ContextCompactedEvent) else None)
    provider = SummaryProvider("## 1. Original Goal\nKeep going")
    compactor = Compactor(bus, tmp_path, "sess-test")
    ctx = ExecutionContext(
        run_id="r1",
        goal="g",
        max_steps=1,
        prefill_messages=[{"role": "user", "content": "x" * 1000}],
    )

    did_compact = await compactor.compact(ctx, provider)

    assert did_compact is True
    assert ctx.messages[0]["content"].startswith("## 1. Original Goal")
    assert ctx.messages[1]["role"] == "assistant"
    assert provider.calls[0]["tool_schemas"] == []
    assert list(tmp_path.glob("summary_*.md"))
    assert events[0].type == "context.compacted"


class LoopProvider:
    def __init__(self, responses: list[LlmResponse]) -> None:
        self._responses = responses
        self.messages_seen: list[list[dict[str, Any]]] = []
        self._idx = 0

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        bus: EventBus,
        run_id: str,
        *,
        step: int = 0,
        system: str | None = None,
    ) -> LlmResponse:
        self.messages_seen.append(list(messages))
        response = self._responses[self._idx]
        self._idx += 1
        return response


class FakeCompactor:
    def __init__(self) -> None:
        self.called = False

    async def compact(self, context: ExecutionContext, provider: Any) -> bool:
        self.called = True
        context.messages = [
            {"role": "user", "content": "summary"},
            {"role": "assistant", "content": "continue"},
        ]
        return True


@pytest.mark.asyncio
async def test_agent_loop_auto_compacts_after_tool_result(tmp_path: Path) -> None:
    target = tmp_path / "data.txt"
    target.write_text("content", encoding="utf-8")
    provider = LoopProvider(
        [
            LlmResponse(
                text="",
                tool_calls=[
                    ToolCall(id="tc1", name="read_file", input={"path": str(target)})
                ],
                stop_reason="tool_use",
                usage=LlmUsage(input_tokens=90, output_tokens=1, context_pct=0.9),
            ),
            LlmResponse(text="done", stop_reason="end_turn"),
        ]
    )
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    bus = EventBus()
    compactor = FakeCompactor()
    loop = AgentLoop(
        provider,
        registry,
        bus,
        compactor=compactor,  # type: ignore[arg-type]
        compact_threshold=0.8,
    )
    ctx = ExecutionContext(run_id="r1", goal="g", max_steps=5)

    await loop.run(ctx)

    assert compactor.called is True
    assert provider.messages_seen[1][0]["content"] == "summary"
    assert any(msg.get("role") == "tool" for msg in ctx.transcript_messages)
