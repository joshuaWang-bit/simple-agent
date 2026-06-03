from __future__ import annotations

import logging
from pathlib import Path
from types import TracebackType
from typing import Self

from pydantic import BaseModel

from simple_agent.core.events.bus import EventBus

logger = logging.getLogger(__name__)


class EventWriter:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._file: logging._FileHandler | None = None

    async def __aenter__(self) -> Self:
        self._file = open(self._path, "w", encoding="utf-8")  # type: ignore[assignment]
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def subscribe(self, bus: EventBus) -> None:
        bus.subscribe(self.handle)

    async def handle(self, event: BaseModel) -> None:
        if self._file is None:
            return
        try:
            self._file.write(event.model_dump_json() + "\n")
            self._file.flush()
        except (OSError, ValueError) as e:
            logger.error("EventWriter: failed to write event: %s", e)
