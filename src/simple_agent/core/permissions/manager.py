from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from simple_agent.core.permissions.policy import (
    PermissionDecision,
    evaluate,
    matches_outside_cwd,
)

logger = logging.getLogger(__name__)


def param_preview(tool_name: str, params: dict[str, Any]) -> str:
    if tool_name == "bash":
        return str(params.get("command", ""))
    parts = []
    for k, v in params.items():
        sv = str(v)
        if len(sv) > 40:
            sv = sv[:37] + "..."
        parts.append(f"{k}={sv!r}")
    return " ".join(parts)


@dataclass
class _PendingRequest:
    future: asyncio.Future[str]
    session_id: str
    tool_name: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_policy_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if isinstance(v, str)}
    except Exception:
        pass
    return {}


def save_policy_file(policies: dict[str, str], path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(policies, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        logger.exception("Failed to save policy file to %s", path)


class PermissionManager:
    def __init__(
        self,
        timeout_s: float = 120.0,
        policy_file: Path | None = None,
    ) -> None:
        self._timeout_s = timeout_s
        self._policy_file = policy_file
        self._pending: dict[str, _PendingRequest] = {}
        self._session_always: dict[tuple[str, str], str] = {}
        self._persistent_always: dict[str, str] = (
            load_policy_file(policy_file) if policy_file else {}
        )

    async def check_and_wait(
        self,
        tool_use_id: str,
        tool_name: str,
        params: dict[str, Any],
        session_id: str,
        event_emitter: Callable[[dict[str, Any]], Any],
    ) -> tuple[bool, str]:
        decision = evaluate(tool_name, params)

        if decision == PermissionDecision.DENY:
            return False, "deny"

        command = str(params.get("command", "")) if tool_name == "bash" else ""
        forced_ask = command and matches_outside_cwd(command)

        if not forced_ask:
            cache_key = (session_id, tool_name)
            cached = self._session_always.get(cache_key)
            if cached == "allow":
                return True, "allow"
            if cached == "deny":
                return False, "deny"

            persistent = self._persistent_always.get(tool_name)
            if persistent == "allow":
                return True, "allow"
            if persistent == "deny":
                return False, "deny"

        if decision == PermissionDecision.ALLOW and not forced_ask:
            return True, "allow"

        # ASK path
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()
        self._pending[tool_use_id] = _PendingRequest(
            future=future,
            session_id=session_id,
            tool_name=tool_name,
        )

        await event_emitter({
            "type": "permission.requested",
            "tool_use_id": tool_use_id,
            "tool_name": tool_name,
            "params": params,
            "param_preview": param_preview(tool_name, params),
            "session_id": session_id,
            "ts": _now(),
        })

        try:
            raw = await asyncio.wait_for(future, timeout=self._timeout_s)
        except TimeoutError:
            self._pending.pop(tool_use_id, None)
            return False, "timeout"

        allowed = self._apply_response(raw, session_id, tool_name)
        return allowed, raw

    def respond(self, tool_use_id: str, decision: str) -> None:
        req = self._pending.pop(tool_use_id, None)
        if req is None:
            logger.warning(
                "permission.respond: unknown tool_use_id=%s", tool_use_id
            )
            return
        if not req.future.done():
            req.future.set_result(decision)

    def _apply_response(self, decision: str, session_id: str, tool_name: str) -> bool:
        allow = decision in ("allow_once", "always_allow")
        if decision == "always_allow":
            self._session_always[(session_id, tool_name)] = "allow"
            self._persistent_always[tool_name] = "allow"
            if self._policy_file is not None:
                save_policy_file(self._persistent_always, self._policy_file)
        elif decision == "always_deny":
            self._session_always[(session_id, tool_name)] = "deny"
            self._persistent_always[tool_name] = "deny"
            if self._policy_file is not None:
                save_policy_file(self._persistent_always, self._policy_file)
        return allow
