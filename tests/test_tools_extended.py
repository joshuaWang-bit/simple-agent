from __future__ import annotations

from pathlib import Path

import pytest

from simple_agent.core.tools.bash import BashTool
from simple_agent.core.tools.list_dir import ListDirTool
from simple_agent.core.tools.write_file import WriteFileTool


@pytest.fixture
def bash_tool() -> BashTool:
    return BashTool()


@pytest.fixture
def write_file_tool() -> WriteFileTool:
    return WriteFileTool()


@pytest.fixture
def list_dir_tool() -> ListDirTool:
    return ListDirTool()


@pytest.mark.asyncio
async def test_bash_echo(bash_tool: BashTool) -> None:
    result = await bash_tool.run({"command": "echo hello"})
    assert result.is_error is False
    assert "hello" in result.content


@pytest.mark.asyncio
async def test_bash_timeout(bash_tool: BashTool) -> None:
    result = await bash_tool.run({"command": "sleep 5", "timeout": 0.1})
    assert result.is_error is True
    assert "timeout" in result.content


@pytest.mark.asyncio
async def test_bash_nonzero_exit(bash_tool: BashTool) -> None:
    result = await bash_tool.run({"command": "exit 1"})
    assert result.is_error is True
    assert "exit 1" in result.content


@pytest.mark.asyncio
async def test_write_file(write_file_tool: WriteFileTool, tmp_path: Path) -> None:
    target = tmp_path / "subdir" / "test.txt"
    result = await write_file_tool.run({"path": str(target), "content": "hello world"})
    assert result.is_error is False
    assert target.read_text(encoding="utf-8") == "hello world"


@pytest.mark.asyncio
async def test_write_file_path_traversal(write_file_tool: WriteFileTool) -> None:
    result = await write_file_tool.run({"path": "../../../etc/passwd", "content": "x"})
    assert result.is_error is True
    assert "traversal" in result.content


@pytest.mark.asyncio
async def test_list_dir(list_dir_tool: ListDirTool, tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b_dir").mkdir()
    (tmp_path / "b_dir" / "c.txt").write_text("c")

    result = await list_dir_tool.run({"path": str(tmp_path), "max_depth": 1})
    assert result.is_error is False
    assert "a.txt" in result.content
    assert "b_dir/" in result.content
    assert "c.txt" in result.content


@pytest.mark.asyncio
async def test_list_dir_not_found(list_dir_tool: ListDirTool) -> None:
    result = await list_dir_tool.run({"path": "/nonexistent/path"})
    assert result.is_error is True
