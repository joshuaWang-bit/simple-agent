from __future__ import annotations

import asyncio
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from simple_agent.core.agents import AgentProfile, AgentProfileLoader
from simple_agent.core.config import AgentConfig
from simple_agent.core.context import ExecutionContext
from simple_agent.core.events.bus import EventBus, EventHandler
from simple_agent.core.events.types import (
    RunFinishedEvent,
    RunStartedEvent,
    SessionClosedEvent,
    SessionWaitingForInputEvent,
    SubagentFinishedEvent,
    SubagentStartedEvent,
)
from simple_agent.core.events.writer import EventWriter
from simple_agent.core.llm.provider import OpenAICompatibleProvider
from simple_agent.core.loop import AgentLoop
from simple_agent.core.memory import load_context_file
from simple_agent.core.mcp import McpServerManager
from simple_agent.core.permissions import PermissionManager
from simple_agent.core.session import Session
from simple_agent.core.session.compactor import Compactor
from simple_agent.core.session.store import SessionStore
from simple_agent.core.task import TaskManager
from simple_agent.core.tools.bash import BashTool
from simple_agent.core.tools.list_dir import ListDirTool
from simple_agent.core.tools.note_save import NoteSaveTool
from simple_agent.core.tools.read_file import ReadFileTool
from simple_agent.core.tools.registry import ToolRegistry
from simple_agent.core.tools.subagent import (
    AgentResultTool,
    BackgroundSubagentRegistry,
    SpawnAgentParams,
    SpawnAgentTool,
)
from simple_agent.core.tools.task_tools import (
    TaskCreateTool,
    TaskGetTool,
    TaskListTool,
    TaskUpdateTool,
)
from simple_agent.core.tools.write_file import WriteFileTool
from simple_agent.core.trace.provider import TracingProvider
from simple_agent.core.trace.writer import TraceWriter


def new_run_id() -> str:
    now = datetime.now(timezone.utc)
    rand = secrets.token_hex(3)
    return now.strftime("%Y%m%d-%H%M%S-") + rand


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentRunner:
    def __init__(
        self,
        config: AgentConfig,
        provider: OpenAICompatibleProvider | None = None,
        extra_handlers: list[EventHandler] | None = None,
        runs_dir: Path | None = None,
        bus: EventBus | None = None,
        trace: TraceWriter | None = None,
        permission_manager: PermissionManager | None = None,
        mcp_manager: McpServerManager | None = None,
        agent_profile_loader: AgentProfileLoader | None = None,
        subagent_depth: int = 0,
        background_subagents: BackgroundSubagentRegistry | None = None,
    ) -> None:
        self._config = config
        self._provider = provider
        self._extra_handlers = extra_handlers or []
        self._runs_dir = runs_dir or Path("runs")
        self._bus = bus
        self._trace = trace
        self._permission_manager = permission_manager
        self._mcp_manager = mcp_manager
        self._agent_profile_loader = agent_profile_loader or AgentProfileLoader()
        self._subagent_depth = subagent_depth
        self._background_subagents = background_subagents or BackgroundSubagentRegistry()

    async def run(
        self,
        goal: str,
        run_id: str | None = None,
        *,
        session: Session | None = None,
        store: SessionStore | None = None,
        system_prompt_override: str | None = None,
        tool_whitelist: list[str] | None = None,
    ) -> None:
        # 1. 为这次运行生成唯一 ID
        run_id = run_id or new_run_id()

        # 2. 确定 run 目录和恢复上下文
        history: list[dict[str, Any]] = []
        notes = ""
        if session is not None and store is not None:
            run_path = store.runs_dir(session.id) / run_id
            run_path.mkdir(parents=True, exist_ok=True)
            history = store.read_messages(session.id)
            if history and history[-1].get("role") == "user":
                history = list(history)
                history[-1] = {**history[-1], "content": goal}
            notes = store.read_notes(session.id)
        else:
            run_path = self._runs_dir / run_id
            run_path.mkdir(parents=True, exist_ok=True)

        # 3. 建立事件总线，订阅所有监听者
        bus = self._bus or EventBus()
        for h in self._extra_handlers:
            bus.subscribe(h)

        # 4. 根据 tier 选择模型，准备 LLM、工具注册表、循环控制器
        model = self._resolve_model()
        provider = self._provider or OpenAICompatibleProvider(
            model=model,
            api_base=self._config.llm_api_base,
            api_key=self._config.llm_api_key,
            enable_thinking=self._config.llm_enable_thinking,
        )

        # 埋点 ④：用 TracingProvider 包装真实 provider
        if self._trace is not None:
            provider = TracingProvider(
                provider,
                self._trace,
                include_payload=self._config.trace_include_llm_payload,
            )

        task_manager = TaskManager(run_path / ".tasks")
        registry = self._build_registry(
            task_manager,
            session,
            store,
            run_id,
            tool_whitelist=tool_whitelist,
            bus=bus,
            provider=provider,
            session_id=session.id if session is not None else None,
        )
        session_dir = store.session_dir(session.id) if session is not None and store is not None else run_path
        compactor = Compactor(
            bus,
            session_dir,
            session.id if session is not None else "",
        )
        loop = AgentLoop(
            provider,
            registry,
            bus,
            permission_manager=self._permission_manager,
            session_id=session.id if session is not None else None,
            compactor=compactor,
            compact_threshold=self._config.compaction_auto_threshold,
        )

        # 5. 创建"工作记忆"
        global_context = load_context_file(Path.home() / ".sagent" / "context.md")
        project_context = load_context_file(Path(".sagent") / "context.md")
        context = ExecutionContext(
            run_id=run_id,
            goal=goal,
            max_steps=self._config.agent_max_steps,
            prefill_messages=history if history else None,
            global_context=global_context,
            project_context=project_context,
            session_notes=notes,
            system_prompt_override=system_prompt_override,
        )

        # 6. 打开事件文件，然后正式开始
        t0 = datetime.now(timezone.utc)
        async with EventWriter(run_path / "events.jsonl") as writer:
            writer.subscribe(bus)
            await bus.publish(
                RunStartedEvent(run_id=run_id, goal=goal, ts=_now())
            )
            await loop.run(context)
            elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
            await bus.publish(
                RunFinishedEvent(
                    run_id=run_id,
                    status=context.status,
                    step_count=context.step,
                    elapsed_s=elapsed,
                    reason=context.reason,
                    ts=_now(),
                )
            )

        # 7. run 结束后写回 session 记忆
        if session is not None and store is not None:
            new_messages = context.transcript_messages[len(history) :]
            for msg in new_messages:
                store.append_message(session.id, msg)

            if session.mode == "one_shot":
                session.status = "closed"
                await bus.publish(
                    SessionClosedEvent(session_id=session.id, ts=_now())
                )
            else:
                session.status = "waiting_for_input"
                await bus.publish(
                    SessionWaitingForInputEvent(session_id=session.id, ts=_now())
                )
            store.write_meta(session)

    def _build_registry(
        self,
        task_manager: TaskManager,
        session: Session | None,
        store: SessionStore | None,
        run_id: str,
        *,
        tool_whitelist: list[str] | None = None,
        bus: EventBus | None = None,
        provider: Any | None = None,
        session_id: str | None = None,
        subagent_depth: int | None = None,
    ) -> ToolRegistry:
        registry = ToolRegistry()
        allowed: set[str] | None = set(tool_whitelist) if tool_whitelist else None
        depth = self._subagent_depth if subagent_depth is None else subagent_depth

        def ok(name: str) -> bool:
            return allowed is None or name in allowed

        for t in [ReadFileTool(), BashTool(), WriteFileTool(), ListDirTool()]:
            if ok(t.name):
                registry.register(t)
        for t in [
            TaskCreateTool(task_manager),
            TaskUpdateTool(task_manager),
            TaskListTool(task_manager),
            TaskGetTool(task_manager),
        ]:
            if ok(t.name):
                registry.register(t)
        if session is not None and store is not None:
            t = NoteSaveTool(store, session.id, run_id)
            if ok(t.name):
                registry.register(t)
        for t in [
            SpawnAgentTool(
                lambda params: self._spawn_subagent(
                    params,
                    parent_run_id=run_id,
                    parent_bus=bus or self._bus or EventBus(),
                    provider=provider,
                    session=session,
                    store=store,
                    session_id=session_id or (session.id if session else None),
                    subagent_depth=depth,
                )
            ),
            AgentResultTool(self._background_subagents),
        ]:
            if ok(t.name):
                registry.register(t)
        if self._mcp_manager is not None:
            for t in self._mcp_manager.get_tools():
                if ok(t.name):
                    registry.register(t)
        return registry

    async def _spawn_subagent(
        self,
        params: SpawnAgentParams,
        *,
        parent_run_id: str,
        parent_bus: EventBus,
        provider: Any | None,
        session: Session | None,
        store: SessionStore | None,
        session_id: str | None,
        subagent_depth: int,
    ) -> ToolResult:
        from simple_agent.core.tools.base import ToolResult

        if subagent_depth >= 2:
            return ToolResult(
                content="Subagent nesting limit (2) reached; cannot spawn further subagents.",
                is_error=True,
                error_type="runtime_error",
            )

        child_run_id = new_run_id()
        profile = (
            self._agent_profile_loader.resolve(params.subagent_type)
            if params.subagent_type
            else None
        )

        if params.run_in_background:
            task = asyncio.create_task(
                self._run_subagent(
                    params,
                    child_run_id=child_run_id,
                    parent_run_id=parent_run_id,
                    parent_bus=parent_bus,
                    provider=provider,
                    session=session,
                    store=store,
                    session_id=session_id,
                    profile=profile,
                    subagent_depth=subagent_depth + 1,
                )
            )
            self._background_subagents.register(child_run_id, task)
            return ToolResult(
                content=(
                    f"Subagent started in background. run_id={child_run_id}. "
                    f"Use agent_result with run_id='{child_run_id}' to retrieve result."
                )
            )

        context = await self._run_subagent(
            params,
            child_run_id=child_run_id,
            parent_run_id=parent_run_id,
            parent_bus=parent_bus,
            provider=provider,
            session=session,
            store=store,
            session_id=session_id,
            profile=profile,
            subagent_depth=subagent_depth + 1,
        )
        if context.status == "failed":
            return ToolResult(
                content=context.result or context.reason or "Subagent failed.",
                is_error=True,
                error_type="runtime_error",
            )
        return ToolResult(
            content=context.result or "Subagent completed with no text result."
        )

    async def _run_subagent(
        self,
        params: SpawnAgentParams,
        *,
        child_run_id: str,
        parent_run_id: str,
        parent_bus: EventBus,
        provider: Any | None,
        session: Session | None,
        store: SessionStore | None,
        session_id: str | None,
        profile: AgentProfile | None,
        subagent_depth: int,
    ) -> ExecutionContext:
        child_bus = EventBus()

        async def bridge(event: BaseModel) -> None:
            await parent_bus.publish(event)

        child_bus.subscribe(bridge)
        if self._trace is not None:
            child_bus.subscribe(self._trace_event_handler)

        if session is not None and store is not None:
            run_path = store.runs_dir(session.id) / child_run_id
        else:
            run_path = self._runs_dir / child_run_id
        run_path.mkdir(parents=True, exist_ok=True)

        await parent_bus.publish(
            SubagentStartedEvent(
                run_id=child_run_id,
                parent_run_id=parent_run_id,
                description=params.description,
                subagent_type=params.subagent_type,
                background=params.run_in_background,
                ts=_now(),
            )
        )

        t0 = time.perf_counter()
        context = ExecutionContext(
            run_id=child_run_id,
            goal=params.prompt,
            max_steps=self._config.agent_max_steps,
            system_prompt_override=profile.system_prompt if profile else None,
            global_context=load_context_file(Path.home() / ".sagent" / "context.md"),
            project_context=load_context_file(Path(".sagent") / "context.md"),
            session_notes=store.read_notes(session.id)
            if session is not None and store is not None
            else "",
        )
        task_manager = TaskManager(run_path / ".tasks")
        registry = self._build_registry(
            task_manager,
            session,
            store,
            child_run_id,
            tool_whitelist=profile.allowed_tools if profile else None,
            bus=child_bus,
            provider=provider,
            session_id=session_id,
            subagent_depth=subagent_depth,
        )
        loop = AgentLoop(
            provider
            or self._provider
            or OpenAICompatibleProvider(
                model=self._resolve_model(),
                api_base=self._config.llm_api_base,
                api_key=self._config.llm_api_key,
                enable_thinking=self._config.llm_enable_thinking,
            ),
            registry,
            child_bus,
            permission_manager=self._permission_manager,
            session_id=session_id,
            compactor=Compactor(
                child_bus,
                store.session_dir(session.id)
                if session is not None and store is not None
                else run_path,
                session.id if session is not None else "",
            ),
            compact_threshold=self._config.compaction_auto_threshold,
        )

        async with EventWriter(run_path / "events.jsonl") as writer:
            writer.subscribe(child_bus)
            await child_bus.publish(
                RunStartedEvent(run_id=child_run_id, goal=params.prompt, ts=_now())
            )
            await loop.run(context)
            elapsed = time.perf_counter() - t0
            await child_bus.publish(
                RunFinishedEvent(
                    run_id=child_run_id,
                    status=context.status,
                    step_count=context.step,
                    elapsed_s=elapsed,
                    reason=context.reason,
                    ts=_now(),
                )
            )

        await parent_bus.publish(
            SubagentFinishedEvent(
                run_id=child_run_id,
                parent_run_id=parent_run_id,
                status=context.status,
                elapsed_s=time.perf_counter() - t0,
                reason=context.reason,
                ts=_now(),
            )
        )
        return context

    async def _trace_event_handler(self, event: BaseModel) -> None:
        if self._trace is None:
            return
        from simple_agent.core.trace.record import TraceRecord

        event_dict = event.model_dump()
        self._trace.emit(
            TraceRecord(
                ts=_now(),
                direction="CORE",
                layer="event",
                kind="event",
                run_id=event_dict.get("run_id"),
                data=event_dict,
            )
        )

    def _build_system_prompt(self) -> str:
        return (
            "You are an autonomous agent. When given a complex goal, "
            "break it down into sub-tasks using task_create. "
            "Set blocked_by dependencies when tasks must wait for others. "
            "Use task_update to mark tasks in_progress and completed. "
            "Use task_list to review progress. "
            "You have access to read_file, write_file, list_dir, and bash tools. "
            "Plan step by step, execute tools, and update task status accordingly."
        )

    def _resolve_model(self) -> str:
        tier = self._config.llm_tier.lower()
        if tier == "ultra":
            return self._config.llm_model_ultra
        if tier == "pro":
            model = self._config.llm_model_pro
            if model:
                return model
            # fallback to fast if pro not configured
            return self._config.llm_model_fast
        return self._config.llm_model_fast
