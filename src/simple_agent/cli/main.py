from __future__ import annotations

import argparse
import sys

from simple_agent.cli.commands.ping import cmd_ping
from simple_agent.cli.commands.run import cmd_run
from simple_agent.cli.commands.version import cmd_version
from simple_agent.core.config import get_config, setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(prog="sagent", description="SimpleAgent CLI")
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("ping", help="Ping the core daemon")

    run_parser = subparsers.add_parser("run", help="Run an agent task")
    run_parser.add_argument("--goal", required=True, help="Task goal/description")
    run_parser.add_argument(
        "--tier", choices=["fast", "pro", "ultra"], help="LLM tier override"
    )

    args = parser.parse_args()

    if args.version:
        cmd_version()
        return

    config = get_config()
    if args.command == "run" and args.tier:
        config.llm_tier = args.tier
    setup_logging(config)

    if args.command == "ping":
        cmd_ping(config)
    elif args.command == "run":
        cmd_run(args.goal, config)
    else:
        parser.print_help()
        sys.exit(1)
