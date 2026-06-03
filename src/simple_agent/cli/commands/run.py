from __future__ import annotations

import asyncio
import sys

from simple_agent.core.config import AgentConfig
from simple_agent.core.printer import StdoutPrinter
from simple_agent.core.runner import AgentRunner


def cmd_run(goal: str, config: AgentConfig) -> None:
    printer = StdoutPrinter()
    runner = AgentRunner(config, extra_handlers=[printer.handle])
    try:
        asyncio.run(runner.run(goal))
    except KeyboardInterrupt:
        sys.exit(130)
