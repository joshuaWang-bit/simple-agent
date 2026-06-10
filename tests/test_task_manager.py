from __future__ import annotations

from pathlib import Path

import pytest

from simple_agent.core.task import TaskManager


@pytest.fixture
def manager(tmp_path: Path) -> TaskManager:
    return TaskManager(tmp_path / ".tasks")


def test_create_task(manager: TaskManager) -> None:
    t = manager.create("分析目录结构", description="了解整体布局")
    assert t.id == 1
    assert t.subject == "分析目录结构"
    assert t.status == "pending"
    assert t.blocked_by == []


def test_create_with_dependency(manager: TaskManager) -> None:
    t1 = manager.create("任务1")
    t2 = manager.create("任务2", blocked_by=[t1.id])
    assert t2.blocked_by == [t1.id]


def test_update_status(manager: TaskManager) -> None:
    t = manager.create("任务")
    updated = manager.update(t.id, status="in_progress")
    assert updated.status == "in_progress"


def test_clear_dependency_on_complete(manager: TaskManager) -> None:
    t1 = manager.create("任务1")
    t2 = manager.create("任务2", blocked_by=[t1.id])
    t3 = manager.create("任务3", blocked_by=[t1.id])

    manager.update(t1.id, status="completed")

    t2_reload = manager.get(t2.id)
    t3_reload = manager.get(t3.id)
    assert t2_reload is not None
    assert t3_reload is not None
    assert t2_reload.blocked_by == []
    assert t3_reload.blocked_by == []


def test_list_tasks(manager: TaskManager) -> None:
    manager.create("A")
    manager.create("B")
    tasks = manager.list()
    assert len(tasks) == 2
    assert tasks[0].id == 1
    assert tasks[1].id == 2


def test_get_missing(manager: TaskManager) -> None:
    assert manager.get(999) is None


def test_persistence(manager: TaskManager, tmp_path: Path) -> None:
    t = manager.create("持久化测试")
    # Create a new manager pointing to the same directory
    manager2 = TaskManager(tmp_path / ".tasks")
    t2 = manager2.get(t.id)
    assert t2 is not None
    assert t2.subject == "持久化测试"
