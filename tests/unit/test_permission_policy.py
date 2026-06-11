from __future__ import annotations

import pytest

from simple_agent.core.permissions.policy import (
    DEFAULT_POLICIES,
    PermissionDecision,
    ToolPolicy,
    evaluate,
    matches_outside_cwd,
)


class TestMatchesOutsideCwd:
    def test_absolute_path(self):
        assert matches_outside_cwd("cat /etc/hostname") is True

    def test_home_path(self):
        assert matches_outside_cwd("cat ~/.bashrc") is True

    def test_parent_traversal(self):
        assert matches_outside_cwd("cat ../README.md") is True

    def test_home_var(self):
        assert matches_outside_cwd("cat $HOME/.ssh/config") is True

    def test_pwd_var(self):
        assert matches_outside_cwd("echo $PWD") is True

    def test_cd_command(self):
        assert matches_outside_cwd("cd /tmp") is True

    def test_cwd_safe(self):
        assert matches_outside_cwd("ls -la") is False
        assert matches_outside_cwd("cat ./file.txt") is False


class TestEvaluate:
    def test_unknown_tool_defaults_to_ask(self):
        assert evaluate("unknown_tool", {}) == PermissionDecision.ASK

    def test_bash_default_ask(self):
        assert evaluate("bash", {"command": "ls"}) == PermissionDecision.ASK

    def test_read_file_default_allow(self):
        assert evaluate("read_file", {"path": "x"}) == PermissionDecision.ALLOW

    def test_deny_pattern(self):
        policy = ToolPolicy(
            default=PermissionDecision.ALLOW,
            deny_patterns=[r"rm\s+-rf\s+/"],
        )
        assert evaluate("bash", {"command": "rm -rf /"}, policy) == PermissionDecision.DENY
        assert evaluate("bash", {"command": "ls"}, policy) == PermissionDecision.ALLOW

    def test_allow_pattern(self):
        policy = ToolPolicy(
            default=PermissionDecision.ASK,
            allow_patterns=[r"^ls\b"],
        )
        assert evaluate("bash", {"command": "ls -la"}, policy) == PermissionDecision.ALLOW
        assert evaluate("bash", {"command": "cat file"}, policy) == PermissionDecision.ASK

    def test_outside_cwd_bypasses_allow_pattern(self):
        """outside-cwd 强制 ASK 不会被 allow pattern 绕过。"""
        policy = ToolPolicy(
            default=PermissionDecision.ASK,
            allow_patterns=[r".*"],
        )
        assert evaluate("bash", {"command": "cat ~/.ssh/config"}, policy) == PermissionDecision.ASK
        assert evaluate("bash", {"command": "cat /etc/hostname"}, policy) == PermissionDecision.ASK

    def test_outside_cwd_after_deny(self):
        policy = ToolPolicy(
            default=PermissionDecision.ALLOW,
            deny_patterns=[r"rm\b"],
        )
        # deny pattern 优先
        assert evaluate("bash", {"command": "rm -rf /tmp"}, policy) == PermissionDecision.DENY
        # outside-cwd 其次
        assert evaluate("bash", {"command": "cat /etc/hostname"}, policy) == PermissionDecision.ASK

    def test_non_bash_tool_ignores_command(self):
        policy = ToolPolicy(default=PermissionDecision.ALLOW)
        assert evaluate("read_file", {"command": "cat /etc/hostname"}, policy) == PermissionDecision.ALLOW


class TestDefaultPolicies:
    def test_bash_is_ask(self):
        assert DEFAULT_POLICIES["bash"].default == PermissionDecision.ASK

    def test_write_file_is_ask(self):
        assert DEFAULT_POLICIES["write_file"].default == PermissionDecision.ASK

    def test_read_file_is_allow(self):
        assert DEFAULT_POLICIES["read_file"].default == PermissionDecision.ALLOW

    def test_list_dir_is_allow(self):
        assert DEFAULT_POLICIES["list_dir"].default == PermissionDecision.ALLOW

    def test_note_save_is_allow(self):
        assert DEFAULT_POLICIES["note_save"].default == PermissionDecision.ALLOW
