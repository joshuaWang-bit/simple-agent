from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from simple_agent.core.config import AgentConfig
from simple_agent.core.events.bus import EventBus
from simple_agent.core.events.types import (
    SkillInvokedEvent,
    SubagentFinishedEvent,
    SubagentStartedEvent,
)
from simple_agent.core.llm.provider import LlmResponse, ToolCall
from simple_agent.core.mcp import McpServerManager, McpToolDefinition
from simple_agent.core.runner import AgentRunner
from simple_agent.core.session.manager import SessionManager
from simple_agent.core.session.store import SessionStore
from simple_agent.core.skills import SkillLoader
from simple_agent.core.task import TaskManager


class QueueProvider:
    def __init__(self, responses: list[LlmResponse]) -> None:
        self._responses = responses
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
                "messages": list(messages),
                "tool_names": [schema["name"] for schema in tool_schemas],
                "run_id": run_id,
                "system": system,
            }
        )
        return self._responses.pop(0)


def test_skill_loader_resolves_builtin_orchestrate() -> None:
    loader = SkillLoader()

    skill = loader.resolve("orchestrate")

    assert skill is not None
    assert "spawn_agent" in skill.allowed_tools
    assert "build it" in loader.render_prompt(skill, "build it")


@pytest.mark.asyncio
async def test_session_slash_command_invokes_skill_and_limits_tools(
    tmp_path: Path,
) -> None:
    provider = QueueProvider([LlmResponse(text="done", stop_reason="end_turn")])
    store = SessionStore(tmp_path)
    bus = EventBus()
    events: list[Any] = []
    bus.subscribe(events.append)

    def runner_factory() -> AgentRunner:
        return AgentRunner(
            AgentConfig(agent_max_steps=2),
            provider=provider,
            bus=bus,
            runs_dir=tmp_path / "runs",
        )

    manager = SessionManager(store, bus, runner_factory)
    session = await manager.create("chat")

    await manager.send_message(session.id, "/orchestrate build it", run_id="run-skill")

    invoked = [event for event in events if isinstance(event, SkillInvokedEvent)]
    assert invoked and invoked[0].skill_name == "orchestrate"
    assert "spawn_agent" in provider.calls[0]["tool_names"]
    assert "read_file" not in provider.calls[0]["tool_names"]
    assert provider.calls[0]["messages"][-1]["content"].startswith(
        "You are a multi-agent coordinator"
    )


@pytest.mark.asyncio
async def test_runner_spawn_agent_foreground_bridges_events(tmp_path: Path) -> None:
    provider = QueueProvider(
        [
            LlmResponse(
                text="",
                tool_calls=[
                    ToolCall(
                        id="tc1",
                        name="spawn_agent",
                        input={
                            "description": "plan",
                            "prompt": "make a plan",
                            "subagent_type": "planner",
                        },
                    )
                ],
                stop_reason="tool_use",
            ),
            LlmResponse(text="child plan", stop_reason="end_turn"),
            LlmResponse(text="parent done", stop_reason="end_turn"),
        ]
    )
    bus = EventBus()
    events: list[Any] = []
    bus.subscribe(events.append)
    runner = AgentRunner(
        AgentConfig(agent_max_steps=5),
        provider=provider,
        bus=bus,
        runs_dir=tmp_path,
    )

    await runner.run("coordinate")

    assert any(isinstance(event, SubagentStartedEvent) for event in events)
    assert any(isinstance(event, SubagentFinishedEvent) for event in events)
    child_call = next(call for call in provider.calls if call["messages"][0]["content"] == "make a plan")
    assert "write_file" not in child_call["tool_names"]
    parent_followup = provider.calls[-1]["messages"][-1]
    assert parent_followup["role"] == "tool"
    assert "child plan" in parent_followup["content"]


@pytest.mark.asyncio
async def test_background_subagent_result_tool(tmp_path: Path) -> None:
    class ResultProvider(QueueProvider):
        def __init__(self) -> None:
            super().__init__([])
            self._parent_step = 0

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
                    "messages": list(messages),
                    "tool_names": [schema["name"] for schema in tool_schemas],
                    "run_id": run_id,
                    "system": system,
                }
            )
            if messages[0]["content"] == "review it":
                return LlmResponse(text="review done", stop_reason="end_turn")

            self._parent_step += 1
            if self._parent_step == 1:
                return LlmResponse(
                    text="",
                    tool_calls=[
                        ToolCall(
                            id="tc1",
                            name="spawn_agent",
                            input={
                                "description": "review",
                                "prompt": "review it",
                                "subagent_type": "reviewer",
                                "run_in_background": True,
                            },
                        )
                    ],
                    stop_reason="tool_use",
                )

            if self._parent_step == 2:
                await asyncio.sleep(0)
                started = [
                    call
                    for call in self.calls
                    if call["messages"][0]["content"] == "review it"
                ]
                assert started
                return LlmResponse(
                    text="",
                    tool_calls=[
                        ToolCall(
                            id="tc2",
                            name="agent_result",
                            input={"run_id": started[0]["run_id"]},
                        )
                    ],
                    stop_reason="tool_use",
                )

            return LlmResponse(text="parent done", stop_reason="end_turn")

    result_provider = ResultProvider()
    runner = AgentRunner(
        AgentConfig(agent_max_steps=6),
        provider=result_provider,
        runs_dir=tmp_path,
    )

    await runner.run("coordinate")

    assert result_provider.calls[-1]["messages"][-1]["role"] == "tool"
    assert "review done" in result_provider.calls[-1]["messages"][-1]["content"]


class FakeMcpClient:
    async def start(self) -> None:
        pass

    async def list_tools(self) -> list[McpToolDefinition]:
        return [
            McpToolDefinition(
                name="lookup",
                description="Lookup a value",
                input_schema={
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                },
            )
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        return f"{name}:{arguments['q']}"

    async def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_mcp_tools_are_injected_and_callable() -> None:
    manager = McpServerManager(client_factory=lambda _cfg: FakeMcpClient())
    await manager.start_all([{"name": "kb", "transport": "tcp", "host": "x", "port": 1}])
    runner = AgentRunner(AgentConfig(), mcp_manager=manager)

    registry = runner._build_registry(TaskManager(Path(".")), None, None, "run-1")

    assert "kb__lookup" in [schema["name"] for schema in registry.tool_schemas()]
    tool = registry.get("kb__lookup")
    assert tool is not None
    result = await tool.run({"q": "abc"})
    assert result.content == "lookup:abc"
