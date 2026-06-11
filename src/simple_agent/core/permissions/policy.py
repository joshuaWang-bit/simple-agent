from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PermissionDecision(Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass
class ToolPolicy:
    default: PermissionDecision = PermissionDecision.ASK
    allow_patterns: list[str] = field(default_factory=list)
    deny_patterns: list[str] = field(default_factory=list)


OUTSIDE_CWD_HEURISTICS = [
    r"(^|\s)/[^\s]",               # absolute path
    r"(^|\s)~",                    # home path
    r"(^|\s)\.\.(/|$|\s)",         # parent traversal
    r"\$\{?HOME\b",
    r"\$\{?PWD\b",
    r"(^|\s|;|&&|\|\|)cd(\s|$)",
]


def matches_outside_cwd(command: str) -> bool:
    for pat in OUTSIDE_CWD_HEURISTICS:
        if re.search(pat, command):
            return True
    return False


DEFAULT_POLICIES: dict[str, ToolPolicy] = {
    "bash": ToolPolicy(default=PermissionDecision.ASK),
    "write_file": ToolPolicy(default=PermissionDecision.ASK),
    "read_file": ToolPolicy(default=PermissionDecision.ALLOW),
    "list_dir": ToolPolicy(default=PermissionDecision.ALLOW),
    "note_save": ToolPolicy(default=PermissionDecision.ALLOW),
}


def evaluate(
    tool_name: str,
    params: dict[str, Any],
    policy: ToolPolicy | None = None,
) -> PermissionDecision:
    if policy is None:
        policy = DEFAULT_POLICIES.get(tool_name)
    if policy is None:
        return PermissionDecision.ASK

    command = str(params.get("command", "")) if tool_name == "bash" else ""

    if command:
        for pat in policy.deny_patterns:
            if re.search(pat, command):
                return PermissionDecision.DENY

    if command and matches_outside_cwd(command):
        return PermissionDecision.ASK

    if command:
        for pat in policy.allow_patterns:
            if re.search(pat, command):
                return PermissionDecision.ALLOW

    return policy.default
