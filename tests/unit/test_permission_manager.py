from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from simple_agent.core.permissions.manager import (
    PermissionManager,
    load_policy_file,
    save_policy_file,
)


@pytest.fixture
def manager() -> PermissionManager:
    return PermissionManager(timeout_s=1.0)


class TestCheckAndWait:
    @pytest.mark.asyncio
    async def test_allow_cache_skip_ask(self, manager: PermissionManager) -> None:
        emitted: list[dict[str, Any]] = []

        async def emitter(raw: dict[str, Any]) -> None:
            emitted.append(raw)

        # No cache -> ASK
        allowed, decision = await manager.check_and_wait(
            "tc1", "bash", {"command": "ls"}, "sess1", emitter
        )
        assert allowed is False  # nobody responded -> timeout
        assert decision == "timeout"

    @pytest.mark.asyncio
    async def test_respond_wakes_future(self, manager: PermissionManager) -> None:
        emitted: list[dict[str, Any]] = []

        async def emitter(raw: dict[str, Any]) -> None:
            emitted.append(raw)

        task = asyncio.create_task(
            manager.check_and_wait("tc2", "bash", {"command": "ls"}, "sess1", emitter)
        )
        # Give the task time to register the future
        await asyncio.sleep(0.05)
        manager.respond("tc2", "allow_once")

        allowed, decision = await task
        assert allowed is True
        assert decision == "allow_once"

    @pytest.mark.asyncio
    async def test_timeout(self, manager: PermissionManager) -> None:
        emitted: list[dict[str, Any]] = []

        async def emitter(raw: dict[str, Any]) -> None:
            emitted.append(raw)

        allowed, decision = await manager.check_and_wait(
            "tc3", "bash", {"command": "ls"}, "sess1", emitter
        )
        assert allowed is False
        assert decision == "timeout"
        assert len(emitted) == 1
        assert emitted[0]["type"] == "permission.requested"

    @pytest.mark.asyncio
    async def test_respond_unknown_id(self, manager: PermissionManager) -> None:
        # Should not raise
        manager.respond("nonexistent", "allow_once")

    @pytest.mark.asyncio
    async def test_always_allow_caches(self, manager: PermissionManager) -> None:
        emitted: list[dict[str, Any]] = []

        async def emitter(raw: dict[str, Any]) -> None:
            emitted.append(raw)

        task = asyncio.create_task(
            manager.check_and_wait("tc4", "bash", {"command": "ls"}, "sess1", emitter)
        )
        await asyncio.sleep(0.05)
        manager.respond("tc4", "always_allow")
        allowed, decision = await task
        assert allowed is True
        assert decision == "always_allow"

        # Second call should hit cache, no event emitted
        allowed2, decision2 = await manager.check_and_wait(
            "tc5", "bash", {"command": "ls"}, "sess1", emitter
        )
        assert allowed2 is True
        assert decision2 == "allow"
        assert len(emitted) == 1  # only the first one emitted

    @pytest.mark.asyncio
    async def test_always_deny_caches(self, manager: PermissionManager) -> None:
        emitted: list[dict[str, Any]] = []

        async def emitter(raw: dict[str, Any]) -> None:
            emitted.append(raw)

        task = asyncio.create_task(
            manager.check_and_wait("tc6", "bash", {"command": "ls"}, "sess1", emitter)
        )
        await asyncio.sleep(0.05)
        manager.respond("tc6", "always_deny")
        allowed, decision = await task
        assert allowed is False
        assert decision == "always_deny"

        allowed2, decision2 = await manager.check_and_wait(
            "tc7", "bash", {"command": "ls"}, "sess1", emitter
        )
        assert allowed2 is False
        assert decision2 == "deny"
        assert len(emitted) == 1

    @pytest.mark.asyncio
    async def test_outside_cwd_bypasses_cache(self, manager: PermissionManager) -> None:
        emitted: list[dict[str, Any]] = []

        async def emitter(raw: dict[str, Any]) -> None:
            emitted.append(raw)

        # First, always allow bash
        task = asyncio.create_task(
            manager.check_and_wait("tc8", "bash", {"command": "ls"}, "sess1", emitter)
        )
        await asyncio.sleep(0.05)
        manager.respond("tc8", "always_allow")
        await task

        # Now outside-cwd should still ASK
        task2 = asyncio.create_task(
            manager.check_and_wait("tc9", "bash", {"command": "cat /etc/hostname"}, "sess1", emitter)
        )
        await asyncio.sleep(0.05)
        manager.respond("tc9", "allow_once")
        allowed, decision = await task2
        assert allowed is True
        assert decision == "allow_once"
        assert len(emitted) == 2

    @pytest.mark.asyncio
    async def test_persistent_cache_shared_across_sessions(self, manager: PermissionManager) -> None:
        emitted: list[dict[str, Any]] = []

        async def emitter(raw: dict[str, Any]) -> None:
            emitted.append(raw)

        task = asyncio.create_task(
            manager.check_and_wait("tc10", "bash", {"command": "ls"}, "sess1", emitter)
        )
        await asyncio.sleep(0.05)
        manager.respond("tc10", "always_allow")
        await task

        # Persistent cache is shared across sessions in the same daemon
        allowed, decision = await manager.check_and_wait(
            "tc11", "bash", {"command": "ls"}, "sess2", emitter
        )
        assert allowed is True
        assert decision == "allow"


class TestPolicyFile:
    def test_load_missing(self, tmp_path: Path) -> None:
        path = tmp_path / "pol.json"
        assert load_policy_file(path) == {}

    def test_save_and_load(self, tmp_path: Path) -> None:
        path = tmp_path / "pol.json"
        save_policy_file({"bash": "allow"}, path)
        assert load_policy_file(path) == {"bash": "allow"}

    def test_persistent_cache_across_instances(self, tmp_path: Path) -> None:
        path = tmp_path / "pol.json"
        m1 = PermissionManager(policy_file=path)
        asyncio.run(_always_allow(m1))

        m2 = PermissionManager(policy_file=path)
        # persistent cache should be loaded
        assert m2._persistent_always.get("bash") == "allow"

    def test_invalid_json_loads_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "pol.json"
        path.write_text("not json")
        assert load_policy_file(path) == {}


async def _always_allow(manager: PermissionManager) -> None:
    async def emitter(raw: dict[str, Any]) -> None:
        pass

    task = asyncio.create_task(
        manager.check_and_wait("tc", "bash", {"command": "ls"}, "sess", emitter)
    )
    await asyncio.sleep(0.05)
    manager.respond("tc", "always_allow")
    await task
