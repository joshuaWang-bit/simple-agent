from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SessionMode = Literal["chat", "one_shot"]


@dataclass
class Session:
    id: str
    mode: SessionMode
    status: str  # "active" | "waiting_for_input" | "closed"
    title: str = ""
    created_at: str = ""
    updated_at: str = ""
    run_ids: list[str] = field(default_factory=list)
