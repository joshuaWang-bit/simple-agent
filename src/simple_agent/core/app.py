from __future__ import annotations

import asyncio
import datetime
import json
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from simple_agent import __version__
from simple_agent.core.bus.commands import PingCommand, PongResult
from simple_agent.core.bus.envelope import EventPushEnvelope
from simple_agent.core.config import get_config, setup_logging
from simple_agent.core.events.bus import EventBus
from simple_agent.core.events.types import RunStartedEvent
from simple_agent.core.llm.provider import OpenAICompatibleProvider
from simple_agent.core.runner import AgentRunner, new_run_id
from simple_agent.core.trace.provider import TracingProvider
from simple_agent.core.trace.record import TraceRecord, _now
from simple_agent.core.trace.writer import TraceWriter
from simple_agent.core.transport.ipc_broadcaster import IpcEventBroadcaster
from simple_agent.core.transport.socket_server import SocketServer, get_connection_writer

logger = logging.getLogger(__name__)


def events_file(run_id: str, runs_dir: Path | None = None) -> Path:
    base = runs_dir or Path("runs")
    return base / run_id / "events.jsonl"


class EventSubscribeCommand(BaseModel):
    topics: list[str]
    scope: str = "global"
    replay_from_run: str | None = None


class EventSubscribeResult(BaseModel):
    subscription_id: str
    replayed_count: int


class AgentRunCommand(BaseModel):
    goal: str


class AgentRunResult(BaseModel):
    run_id: str


class CoreApp:
    def __init__(self, provider: OpenAICompatibleProvider | None = None) -> None:
        self._start_time = time.monotonic()
        self._config = get_config()
        setup_logging(self._config)

        self._bus = EventBus()
        self._broadcaster = IpcEventBroadcaster()
        self._bus.subscribe(self._broadcaster.handle)
        self._current_run_task: asyncio.Task[None] | None = None
        self._provider = provider
        self._trace: TraceWriter | None = None

    async def run(self) -> None:
        # 初始化 trace（如果启用）
        if self._config.trace_enabled:
            trace_path = Path(self._config.trace_file).expanduser()
            self._trace = TraceWriter(trace_path)
            await self._trace.start()
            self._bus.subscribe(self._trace_event_handler)
            self._broadcaster = IpcEventBroadcaster(trace=self._trace)
            self._bus.subscribe(self._broadcaster.handle)
        else:
            self._broadcaster = IpcEventBroadcaster()
            self._bus.subscribe(self._broadcaster.handle)

        server = SocketServer(
            self._config.host, self._config.port, trace=self._trace
        )
        server.set_broadcaster(self._broadcaster)
        server.register("core.ping", self._ping_handler)
        server.register("event.subscribe", self._subscribe_handler)
        server.register("agent.run", self._agent_run_handler)

        addr = await server.start()
        logger.info("sagent-core %s listening addr=%s", __version__, addr)

        shutdown = asyncio.Event()
        loop = asyncio.get_running_loop()
        if sys.platform == "win32":
            signal.signal(signal.SIGINT, lambda _s, _f: shutdown.set())
        else:
            loop.add_signal_handler(signal.SIGINT, shutdown.set)
            loop.add_signal_handler(signal.SIGTERM, shutdown.set)

        await shutdown.wait()
        await server.stop()

        if self._trace is not None:
            await self._trace.stop()

    async def _trace_event_handler(self, event: BaseModel) -> None:
        assert self._trace is not None
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

    async def _ping_handler(self, params: dict[str, Any]) -> PongResult:
        cmd = PingCommand.model_validate(params)
        logger.debug("ping from %s", cmd.client)
        return PongResult(
            server_version=__version__,
            uptime_ms=int((time.monotonic() - self._start_time) * 1000),
            received_at=datetime.datetime.now(datetime.UTC).isoformat(),
        )

    async def _subscribe_handler(self, params: dict[str, Any]) -> EventSubscribeResult:
        cmd = EventSubscribeCommand.model_validate(params)
        writer = get_connection_writer()

        replayed_count = 0
        if cmd.replay_from_run is not None:
            replayed_count = await self._replay_events(
                cmd.replay_from_run, writer, cmd.topics
            )

        sub_id = self._broadcaster.subscribe(writer, cmd.topics, cmd.scope)
        return EventSubscribeResult(subscription_id=sub_id, replayed_count=replayed_count)

    async def _agent_run_handler(self, params: dict[str, Any]) -> AgentRunResult:
        cmd = AgentRunCommand.model_validate(params)

        if self._current_run_task and not self._current_run_task.done():
            raise RuntimeError("a run is already in progress")

        run_id = new_run_id()
        runner = AgentRunner(
            self._config, bus=self._bus, provider=self._provider, trace=self._trace
        )
        self._current_run_task = asyncio.create_task(
            runner.run(cmd.goal, run_id=run_id)
        )
        return AgentRunResult(run_id=run_id)

    async def _replay_events(
        self, run_id: str, writer: asyncio.StreamWriter, topics: list[str]
    ) -> int:
        import fnmatch

        path = events_file(run_id)
        if not path.exists():
            return 0

        count = 0
        for line in path.read_text().splitlines():
            event = json.loads(line)
            event_type = event.get("type", "")
            if not any(fnmatch.fnmatch(event_type, p) for p in topics):
                continue
            envelope = EventPushEnvelope(event=event)
            writer.write(envelope.model_dump_json().encode() + b"\n")
            count += 1

        if count:
            await writer.drain()
        return count


def run() -> None:
    app = CoreApp()
    asyncio.run(app.run())
