from __future__ import annotations

import asyncio
import fnmatch
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from simple_agent.core.bus.envelope import EventPushEnvelope

logger = logging.getLogger(__name__)


@dataclass
class _Subscription:
    sub_id: str
    writer: asyncio.StreamWriter
    topics: list[str] = field(default_factory=list)
    scope: str = "global"


class IpcEventBroadcaster:
    def __init__(self) -> None:
        self._subscriptions: list[_Subscription] = []

    def subscribe(
        self, writer: asyncio.StreamWriter, topics: list[str], scope: str
    ) -> str:
        sub_id = str(uuid.uuid4())[:8]
        self._subscriptions.append(
            _Subscription(sub_id=sub_id, writer=writer, topics=topics, scope=scope)
        )
        return sub_id

    def unsubscribe(self, writer: asyncio.StreamWriter) -> None:
        self._subscriptions = [
            s for s in self._subscriptions if s.writer is not writer
        ]

    async def handle(self, event: BaseModel) -> None:
        event_dict = event.model_dump()
        event_type = event_dict.get("type", "")
        run_id = event_dict.get("run_id")

        dead: list[asyncio.StreamWriter] = []

        for sub in list(self._subscriptions):
            if not self._matches_topic(event_type, sub.topics):
                continue
            if not self._matches_scope(run_id, sub.scope):
                continue
            try:
                envelope = EventPushEnvelope(event=event_dict)
                sub.writer.write(envelope.model_dump_json().encode() + b"\n")
                await sub.writer.drain()
            except (ConnectionResetError, BrokenPipeError, OSError):
                dead.append(sub.writer)

        for writer in dead:
            self.unsubscribe(writer)

    @staticmethod
    def _matches_topic(event_type: str, topics: list[str]) -> bool:
        for pat in topics:
            if fnmatch.fnmatch(event_type, pat):
                return True
        return False

    @staticmethod
    def _matches_scope(run_id: str | None, scope: str) -> bool:
        if scope == "global":
            return True
        if scope.startswith("run:"):
            return run_id == scope[4:]
        return False
