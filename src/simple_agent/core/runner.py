from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from simple_agent.core.config import AgentConfig
from simple_agent.core.context import ExecutionContext
from simple_agent.core.events.bus import EventBus, EventHandler
from simple_agent.core.events.types import RunFinishedEvent, RunStartedEvent
from simple_agent.core.events.writer import EventWriter
from simple_agent.core.llm.provider import OpenAICompatibleProvider
from simple_agent.core.loop import AgentLoop
from simple_agent.core.tools.read_file import ReadFileTool
from simple_agent.core.tools.registry import ToolRegistry
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

    async def run(self, goal: str, run_id: str | None = None) -> None:
        # 1. 为这次运行生成唯一 ID，创建对应目录
        run_id = run_id or new_run_id()
        run_path = self._runs_dir / run_id
        run_path.mkdir(parents=True, exist_ok=True)

        # 2. 建立事件总线，订阅所有监听者
        bus = self._bus or EventBus()
        for h in self._extra_handlers:
            bus.subscribe(h)

        # 3. 根据 tier 选择模型，准备 LLM、工具注册表、循环控制器
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

        registry = ToolRegistry()
        registry.register(ReadFileTool())
        loop = AgentLoop(provider, registry, bus)

        # 4. 创建"工作记忆"，goal 在这里成为第一条消息
        context = ExecutionContext(
            run_id=run_id,
            goal=goal,
            max_steps=self._config.agent_max_steps,
        )

        # 5. 打开事件文件，然后正式开始
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
