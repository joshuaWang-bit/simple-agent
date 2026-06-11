from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AgentProfile:
    name: str
    description: str
    system_prompt: str
    allowed_tools: list[str]
    path: Path


class AgentProfileLoader:
    def __init__(
        self,
        *,
        project_dir: Path | None = None,
        home_dir: Path | None = None,
        builtin_dir: Path | None = None,
    ) -> None:
        self._project_dir = project_dir or Path.cwd()
        self._home_dir = home_dir or Path.home()
        self._builtin_dir = builtin_dir or Path(__file__).with_name("builtin")

    def resolve(self, name: str) -> AgentProfile | None:
        safe_name = _safe_name(name)
        if safe_name is None:
            return None

        for base in self._search_dirs():
            path = base / f"{safe_name}.toml"
            if path.exists():
                return self._load(path, fallback_name=safe_name)
        return None

    def _search_dirs(self) -> list[Path]:
        return [
            self._project_dir / ".sagent" / "agents",
            self._project_dir / ".kama" / "agents",
            self._home_dir / ".sagent" / "agents",
            self._home_dir / ".kama" / "agents",
            self._builtin_dir,
        ]

    def _load(self, path: Path, *, fallback_name: str) -> AgentProfile:
        with path.open("rb") as f:
            data = tomllib.load(f)
        agent: dict[str, Any] = data.get("agent", data)
        allowed = agent.get("allowed_tools") or []
        if not isinstance(allowed, list):
            allowed = []
        return AgentProfile(
            name=str(agent.get("name") or fallback_name),
            description=str(agent.get("description") or ""),
            system_prompt=str(agent.get("system_prompt") or ""),
            allowed_tools=[str(item) for item in allowed],
            path=path,
        )


def _safe_name(name: str) -> str | None:
    if not name:
        return None
    if any(ch in name for ch in ("/", "\\", ".", ":")):
        return None
    return name
