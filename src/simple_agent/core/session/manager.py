from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from simple_agent.core.events.bus import EventBus
from simple_agent.core.events.types import (
    SessionClosedEvent,
    SessionCreatedEvent,
    SessionMessageReceivedEvent,
    SessionResumedEvent,
    SessionWaitingForInputEvent,
)
from simple_agent.core.runner import AgentRunner
from simple_agent.core.session import Session, SessionMode
from simple_agent.core.session.store import SessionStore


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
    ) -> None:
        self._store = store
        self._bus = bus
        self._runner_factory = runner_factory
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

            self._store.append_message(sid, {"role": "user", "content": content})
            await self._bus.publish(
                SessionMessageReceivedEvent(
                    session_id=sid, role="user", content=content, ts=_now()
                )
            )

            rid = run_id or new_run_id()
            session.run_ids.append(rid)
            session.updated_at = _now()
            self._store.write_meta(session)

            runner = self._runner_factory()
            await runner.run(content, run_id=rid, session=session, store=self._store)
            return rid
