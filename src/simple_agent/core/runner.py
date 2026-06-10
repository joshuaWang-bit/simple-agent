from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from simple_agent.core.config import AgentConfig
from simple_agent.core.context import ExecutionContext
from simple_agent.core.events.bus import EventBus, EventHandler
from simple_agent.core.events.types import (
    RunFinishedEvent,
    RunStartedEvent,
    SessionClosedEvent,
    SessionWaitingForInputEvent,
)
from simple_agent.core.events.writer import EventWriter
from simple_agent.core.llm.provider import OpenAICompatibleProvider
from simple_agent.core.loop import AgentLoop
from simple_agent.core.session import Session
from simple_agent.core.session.store import SessionStore
from simple_agent.core.task import TaskManager
from simple_agent.core.tools.bash import BashTool
from simple_agent.core.tools.list_dir import ListDirTool
from simple_agent.core.tools.note_save import NoteSaveTool
from simple_agent.core.tools.read_file import ReadFileTool
from simple_agent.core.tools.registry import ToolRegistry
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
    ) -> None:
        self._config = config
        self._provider = provider
        self._extra_handlers = extra_handlers or []
        self._runs_dir = runs_dir or Path("runs")
        self._bus = bus
        self._trace = trace

    async def run(
        self,
        goal: str,
        run_id: str | None = None,
        *,
        session: Session | None = None,
        store: SessionStore | None = None,
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
        registry = self._build_registry(task_manager, session, store, run_id)
        loop = AgentLoop(provider, registry, bus)

        # 5. 创建"工作记忆"
        context = ExecutionContext(
            run_id=run_id,
            goal=goal,
            max_steps=self._config.agent_max_steps,
            prefill_messages=history if history else None,
            session_notes=notes,
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
            new_messages = context.messages[len(history) :]
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
    ) -> ToolRegistry:
        registry = ToolRegistry()
        for t in [ReadFileTool(), BashTool(), WriteFileTool(), ListDirTool()]:
            registry.register(t)
        for t in [
            TaskCreateTool(task_manager),
            TaskUpdateTool(task_manager),
            TaskListTool(task_manager),
            TaskGetTool(task_manager),
        ]:
            registry.register(t)
        if session is not None and store is not None:
            registry.register(NoteSaveTool(store, session.id, run_id))
        return registry

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
