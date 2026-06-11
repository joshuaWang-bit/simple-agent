from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from simple_agent.core.bus.envelope import HandlerError
from simple_agent.core.events.bus import EventBus
from simple_agent.core.events.types import (
    ContextCompactedEvent,
    SessionClosedEvent,
    SessionCreatedEvent,
    SessionMessageReceivedEvent,
    SessionResumedEvent,
    SessionWaitingForInputEvent,
    SkillInvokedEvent,
)
from simple_agent.core.runner import AgentRunner
from simple_agent.core.session import Session, SessionMode
from simple_agent.core.session.compactor import Compactor, summary_messages
from simple_agent.core.session.store import SessionStore
from simple_agent.core.skills import SkillLoader


def new_run_id() -> str:
    now = datetime.now(timezone.utc)
    rand = secrets.token_hex(3)
    return now.strftime("%Y%m%d-%H%M%S-") + rand


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionManager:
    def __init__(
        self,
        store: SessionStore,
        bus: EventBus,
        runner_factory: Callable[[], AgentRunner],
        skill_loader: SkillLoader | None = None,
    ) -> None:
        self._store = store
        self._bus = bus
        self._runner_factory = runner_factory
        self._skill_loader = skill_loader or SkillLoader()
        self._sessions: dict[str, Session] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def create(self, mode: SessionMode, title: str = "") -> Session:
        sid = f"sess-{secrets.token_hex(6)}"
        ts = _now()
        session = Session(
            id=sid,
            mode=mode,
            status="active",
            title=title,
            created_at=ts,
            updated_at=ts,
            run_ids=[],
        )
        self._sessions[sid] = session
        self._locks[sid] = asyncio.Lock()
        self._store.write_meta(session)
        await self._bus.publish(SessionCreatedEvent(session_id=sid, mode=mode, ts=ts))
        return session

    def get_session(self, sid: str) -> Session:
        if sid not in self._sessions:
            raise ValueError(f"session not found: {sid}")
        return self._sessions[sid]

    async def send_message(
        self, sid: str, content: str, *, run_id: str | None = None
    ) -> str:
        session = self.get_session(sid)
        lock = self._locks.get(sid)
        if lock is None:
            raise ValueError(f"session lock not found: {sid}")
        if lock.locked():
            raise ValueError("session busy")

        async with lock:
            if session.status == "closed":
                raise ValueError("session already closed")

            if session.status == "waiting_for_input":
                await self._bus.publish(SessionResumedEvent(session_id=sid, ts=_now()))

            rid = run_id or new_run_id()
            goal = content
            system_prompt_override: str | None = None
            tool_whitelist: list[str] | None = None

            if content.startswith("/"):
                parts = content[1:].split(None, 1)
                skill_name = parts[0] if parts else ""
                arguments = parts[1] if len(parts) > 1 else ""
                skill = self._skill_loader.resolve(skill_name)
                if skill is not None:
                    goal = self._skill_loader.render_prompt(skill, arguments)
                    system_prompt_override = goal
                    tool_whitelist = skill.allowed_tools or None
                    await self._bus.publish(
                        SkillInvokedEvent(
                            session_id=sid,
                            run_id=rid,
                            skill_name=skill.name,
                            arguments=arguments,
                            tool_whitelist=skill.allowed_tools,
                            ts=_now(),
                        )
                    )

            self._store.append_message(sid, {"role": "user", "content": content})
            await self._bus.publish(
                SessionMessageReceivedEvent(
                    session_id=sid, role="user", content=content, ts=_now()
                )
            )

            session.run_ids.append(rid)
            session.updated_at = _now()
            self._store.write_meta(session)

            runner = self._runner_factory()
            await runner.run(
                goal,
                run_id=rid,
                session=session,
                store=self._store,
                system_prompt_override=system_prompt_override,
                tool_whitelist=tool_whitelist,
            )
            return rid

    async def compact(self, sid: str, provider: Any, *, focus: str = "") -> None:
        session = self.get_session(sid)
        lock = self._locks.get(sid)
        if lock is None:
            raise HandlerError(-32020, f"session lock not found: {sid}")
        if lock.locked():
            raise HandlerError(-32022, "session busy")

        async with lock:
            if session.status == "closed":
                raise HandlerError(-32023, "session already closed")

            messages = self._store.read_messages(sid)
            compactor = Compactor(self._bus, self._store.session_dir(sid), sid)
            result = await compactor.compact_messages(messages, provider, focus=focus)
            if result is None:
                raise HandlerError(-32021, "compaction failed or not beneficial")

            self._store.write_compacted(sid, summary_messages(result.summary_text))
            summary_path = compactor.write_summary(result.summary_text)
            session.updated_at = _now()
            self._store.write_meta(session)
            await self._bus.publish(
                ContextCompactedEvent(
                    session_id=sid,
                    original_tokens=result.original_tokens,
                    summary_tokens=result.summary_tokens,
                    summary_path=str(summary_path),
                    persistent=True,
                    ts=_now(),
                )
            )
