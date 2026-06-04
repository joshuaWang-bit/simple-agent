from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TraceRecord(BaseModel):
    ts: str
    direction: Literal[
        "CLIENT→CORE", "CORE→CLIENT", "CORE", "CORE→LLM", "LLM→CORE"
    ]
    layer: Literal["ipc", "event", "llm"]
    kind: str
    run_id: str | None = None
    step: int | None = None
    client_id: str | None = None
    data: dict[str, Any] = {}
