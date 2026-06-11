from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolResult:
    content: str
    is_error: bool = False
    error_type: str | None = None


class BaseTool(ABC):
    params_model: type | None = None

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def schema(self) -> dict[str, Any]: ...

    @abstractmethod
    async def run(self, input: dict[str, Any]) -> ToolResult: ...
