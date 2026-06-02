from __future__ import annotations

import sys
import time
from unittest.mock import patch

import pytest

from simple_agent import __version__
from simple_agent.cli.commands.ping import _ping
from simple_agent.cli.commands.version import cmd_version
from simple_agent.cli.main import main
from simple_agent.core.bus.commands import PongResult
from simple_agent.core.config import AgentConfig
from simple_agent.core.transport.socket_server import SocketServer


@pytest.fixture
def config() -> AgentConfig:
    return AgentConfig(host="127.0.0.1", port=17437)


@pytest.mark.asyncio
async def test_cli_ping(config: AgentConfig, capsys) -> None:
    """Test actual CLI ping command against a running server."""
    start_time = time.monotonic()

    async def ping_handler(params: dict) -> PongResult:
        return PongResult(
            server_version=__version__,
            uptime_ms=int((time.monotonic() - start_time) * 1000),
            received_at="2026-06-02T09:00:00",
        )

    server = SocketServer(config.host, config.port)
    server.register("core.ping", ping_handler)
    await server.start()

    try:
        await _ping(config)
    finally:
        await server.stop()

    captured = capsys.readouterr()
    assert captured.out.startswith("pong server=0.0.1 uptime=")
    assert "latency=" in captured.out


def test_cli_version(capsys) -> None:
    """Test CLI --version output."""
    cmd_version()
    captured = capsys.readouterr()
    assert captured.out.strip() == __version__


def test_cli_main_no_args(capsys) -> None:
    """Test CLI with no arguments prints help and exits."""
    with patch.object(sys, "argv", ["sagent"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "usage:" in captured.err or "usage:" in captured.out
