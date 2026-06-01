from __future__ import annotations

import asyncio
import datetime
import logging
import signal
import sys
import time
from typing import Any

from simple_agent import __version__
from simple_agent.core.bus.commands import PingCommand, PongResult
from simple_agent.core.config import get_config, setup_logging
from simple_agent.core.transport.socket_server import SocketServer

logger = logging.getLogger(__name__)


class CoreApp:
    async def run(self) -> None:
        self._start_time = time.monotonic()
        config = get_config()
        setup_logging(config)

        server = SocketServer(config.host, config.port)
        server.register("core.ping", self._ping_handler)

        addr = await server.start()
        logger.info("sagent-core %s listening addr=%s", __version__, addr)

        shutdown = asyncio.Event()
        loop = asyncio.get_running_loop()
        if sys.platform == "win32":
            signal.signal(signal.SIGINT, lambda _s, _f: shutdown.set())
        else:
            loop.add_signal_handler(signal.SIGINT, shutdown.set)
            loop.add_signal_handler(signal.SIGTERM, shutdown.set)

        await shutdown.wait()
        await server.stop()

    async def _ping_handler(self, params: dict[str, Any]) -> PongResult:
        cmd = PingCommand.model_validate(params)
        logger.debug("ping from %s", cmd.client)
        return PongResult(
            server_version=__version__,
            uptime_ms=int((time.monotonic() - self._start_time) * 1000),
            received_at=datetime.datetime.now(datetime.UTC).isoformat(),
        )


def run() -> None:
    app = CoreApp()
    asyncio.run(app.run())
