from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from simple_agent.core.context import ExecutionContext
from simple_agent.core.events import EventBus, EventWriter
from simple_agent.core.events.types import RunStartedEvent
from simple_agent.core.llm.provider import LlmResponse, ToolCall
from simple_agent.core.loop import AgentLoop
from simple_agent.core.printer import StdoutPrinter
from simple_agent.core.runner import AgentRunner, new_run_id
from simple_agent.core.tools import ReadFileTool, ToolRegistry, invoke_tool


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_event_bus_publish() -> None:
    bus = EventBus()
    received: list[str] = []

    async def handler(event: Any) -> None:
        received.append(event.run_id)

    bus.subscribe(handler)
    await bus.publish(RunStartedEvent(run_id="r1", goal="g", ts="t"))
    assert received == ["r1"]


# ---------------------------------------------------------------------------
# EventWriter
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_event_writer(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    writer = EventWriter(path)
    async with writer:
        await writer.handle(RunStartedEvent(run_id="r1", goal="g", ts="t"))

    lines = path.read_text().strip().split("\n")
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["type"] == "run.started"
    assert data["run_id"] == "r1"


# ---------------------------------------------------------------------------
# ExecutionContext
# ---------------------------------------------------------------------------
def test_execution_context_init() -> None:
    ctx = ExecutionContext(run_id="r1", goal="hello", max_steps=5)
    assert ctx.status == "running"
    assert ctx.step == 0
    assert len(ctx.messages) == 1
    assert ctx.messages[0]["role"] == "user"
    assert ctx.messages[0]["content"] == "hello"


def test_execution_context_add_assistant_message() -> None:
    ctx = ExecutionContext(run_id="r1", goal="hello", max_steps=5)
    ctx.add_assistant_message("hi")
    assert len(ctx.messages) == 2
    assert ctx.messages[1]["role"] == "assistant"
    assert ctx.messages[1]["content"] == "hi"


def test_execution_context_add_assistant_with_tool_calls() -> None:
    ctx = ExecutionContext(run_id="r1", goal="hello", max_steps=5)
    ctx.add_assistant_message(
        "",
        tool_calls=[
            {"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}
        ],
    )
    assert len(ctx.messages) == 2
    assert ctx.messages[1]["role"] == "assistant"
    assert ctx.messages[1]["tool_calls"][0]["id"] == "c1"


def test_execution_context_add_tool_result() -> None:
    ctx = ExecutionContext(run_id="r1", goal="hello", max_steps=5)
    ctx.add_tool_result("c1", "result1")
    assert len(ctx.messages) == 2
    assert ctx.messages[1]["role"] == "tool"
    assert ctx.messages[1]["tool_call_id"] == "c1"


def test_execution_context_done() -> None:
    ctx = ExecutionContext(run_id="r1", goal="hello", max_steps=5)
    assert not ctx.is_done()
    ctx.mark_success()
    assert ctx.is_done()
    assert ctx.status == "success"

    ctx2 = ExecutionContext(run_id="r2", goal="hello", max_steps=5)
    ctx2.mark_failed("oops")
    assert ctx2.is_done()
    assert ctx2.status == "failed"
    assert ctx2.reason == "oops"


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------
def test_tool_registry() -> None:
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    assert len(registry.tool_schemas()) == 1
    assert registry.get("read_file") is not None
    assert registry.get("missing") is None


# ---------------------------------------------------------------------------
# ReadFileTool
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_read_file_tool(tmp_path: Path) -> None:
    f = tmp_path / "test.txt"
    f.write_text("hello world")
    tool = ReadFileTool()
    result = await tool.run({"path": str(f)})
    assert result.content == "hello world"
    assert not result.is_error


@pytest.mark.asyncio
async def test_read_file_tool_error() -> None:
    tool = ReadFileTool()
    result = await tool.run({"path": "/nonexistent/file.txt"})
    assert result.is_error


# ---------------------------------------------------------------------------
# invoke_tool
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_invoke_tool_unknown() -> None:
    registry = ToolRegistry()
    bus = EventBus()
    tc = ToolCall(id="t1", name="unknown", input={})
    result = await invoke_tool(registry, tc, bus, "r1")
    assert result.is_error
    assert "Unknown tool" in result.content


@pytest.mark.asyncio
async def test_invoke_tool_ok(tmp_path: Path) -> None:
    f = tmp_path / "test.txt"
    f.write_text("data")
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    bus = EventBus()
    tc = ToolCall(id="t1", name="read_file", input={"path": str(f)})
    result = await invoke_tool(registry, tc, bus, "r1")
    assert result.content == "data"
    assert not result.is_error


# ---------------------------------------------------------------------------
# AgentLoop
# ---------------------------------------------------------------------------
class FakeProvider:
    def __init__(self, responses: list[LlmResponse]) -> None:
        self._responses = responses
        self._idx = 0

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        bus: EventBus,
        run_id: str,
    ) -> LlmResponse:
        resp = self._responses[self._idx]
        self._idx += 1
        return resp


@pytest.mark.asyncio
async def test_agent_loop_end_turn() -> None:
    provider = FakeProvider([LlmResponse(text="done", stop_reason="end_turn")])
    registry = ToolRegistry()
    bus = EventBus()
    loop = AgentLoop(provider, registry, bus)
    ctx = ExecutionContext(run_id="r1", goal="g", max_steps=5)
    await loop.run(ctx)
    assert ctx.status == "success"
    assert ctx.step == 1


@pytest.mark.asyncio
async def test_agent_loop_max_steps() -> None:
    provider = FakeProvider(
        [LlmResponse(text="x", stop_reason="") for _ in range(3)]
    )
    registry = ToolRegistry()
    bus = EventBus()
    loop = AgentLoop(provider, registry, bus)
    ctx = ExecutionContext(run_id="r1", goal="g", max_steps=2)
    await loop.run(ctx)
    assert ctx.status == "failed"
    assert ctx.reason == "exceeded_max_steps"


@pytest.mark.asyncio
async def test_agent_loop_tool_use(tmp_path: Path) -> None:
    f = tmp_path / "test.txt"
    f.write_text("file content")
    provider = FakeProvider(
        [
            LlmResponse(
                text="",
                tool_calls=[ToolCall(id="t1", name="read_file", input={"path": str(f)})],
                stop_reason="tool_use",
            ),
            LlmResponse(text="done", stop_reason="end_turn"),
        ]
    )
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    bus = EventBus()
    loop = AgentLoop(provider, registry, bus)
    ctx = ExecutionContext(run_id="r1", goal="g", max_steps=5)
    await loop.run(ctx)
    assert ctx.status == "success"
    assert ctx.step == 2


# ---------------------------------------------------------------------------
# AgentRunner
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_agent_runner(tmp_path: Path) -> None:
    from simple_agent.core.config import AgentConfig

    config = AgentConfig(agent_max_steps=2)
    provider = FakeProvider(
        [LlmResponse(text="done", stop_reason="end_turn")]
    )
    runner = AgentRunner(
        config,
        provider=provider,
        runs_dir=tmp_path,
    )
    await runner.run("test goal")

    run_dirs = list(tmp_path.iterdir())
    assert len(run_dirs) == 1
    events_file = run_dirs[0] / "events.jsonl"
    assert events_file.exists()


# ---------------------------------------------------------------------------
# new_run_id
# ---------------------------------------------------------------------------
def test_new_run_id() -> None:
    rid = new_run_id()
    assert len(rid.split("-")) == 3


# ---------------------------------------------------------------------------
# StdoutPrinter
# ---------------------------------------------------------------------------
def test_stdout_printer_run_started(capsys) -> None:
    printer = StdoutPrinter()
    printer.handle(RunStartedEvent(run_id="r1", goal="g", ts="t"))
    captured = capsys.readouterr()
    assert "[run] r1" in captured.out
