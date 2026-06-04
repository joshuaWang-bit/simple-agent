from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from simple_agent.core.config import AgentConfig


# ANSI color codes
_COLOR_DIM = "\033[2m"
_COLOR_RESET = "\033[0m"
_COLOR_RED = "\033[31m"
_COLOR_GREEN = "\033[32m"
_COLOR_YELLOW = "\033[33m"
_COLOR_BLUE = "\033[34m"
_COLOR_MAGENTA = "\033[35m"
_COLOR_CYAN = "\033[36m"

_DIRECTION_COLORS = {
    "CLIENT→CORE": _COLOR_GREEN,
    "CORE→CLIENT": _COLOR_BLUE,
    "CORE": _COLOR_YELLOW,
    "CORE→LLM": _COLOR_MAGENTA,
    "LLM→CORE": _COLOR_CYAN,
}


def _color_direction(direction: str) -> str:
    color = _DIRECTION_COLORS.get(direction, "")
    return f"{color}{direction}{_COLOR_RESET}"


def _summarize(record: dict[str, Any]) -> str:
    kind = record.get("kind", "")
    data = record.get("data", {})
    direction = record.get("direction", "")

    if kind == "command":
        method = data.get("method", "")
        params = data.get("params", {})
        if method == "agent.run":
            goal = params.get("goal", "")
            return f"method={method} goal={goal!r}"
        return f"method={method}"

    if kind == "response":
        result = data.get("result", {})
        if "run_id" in result:
            return f"run_id={result['run_id']}"
        return f"id={data.get('id', '')}"

    if kind == "push":
        return f"event={data.get('event_type', '')} sub={data.get('sub_id', '')}"

    if kind == "event":
        return f"type={data.get('type', '')}"

    if kind == "api_call":
        if "message_count" in data:
            return f"msgs={data['message_count']} tools={data['tool_count']}"
        return f"msgs={len(data.get('messages', []))} tools={len(data.get('tool_schemas', []))}"

    if kind == "api_response":
        parts = [f"stop={data.get('stop_reason', '')}"]
        if "latency_ms" in data:
            parts.append(f"latency={data['latency_ms']}ms")
        if "out_tokens" in data:
            parts.append(f"out_tokens={data['out_tokens']}")
        elif "tool_count" in data:
            parts.append(f"tools={data['tool_count']}")
        return " ".join(parts)

    return json.dumps(data, ensure_ascii=False)


def _print_record(record: dict[str, Any]) -> None:
    ts = record.get("ts", "")
    # 截取时间部分
    if "T" in ts:
        ts = ts.split("T")[1]
    if "." in ts:
        ts = ts[:12]

    direction = record.get("direction", "")
    kind = record.get("kind", "")
    summary = _summarize(record)

    print(
        f"{_COLOR_DIM}{ts}{_COLOR_RESET}  "
        f"{_color_direction(direction):<18}  "
        f"{kind:<14}  "
        f"{summary}"
    )


def _match(record: dict[str, Any], run_id: str | None, layer: str | None) -> bool:
    if run_id is not None and record.get("run_id") != run_id:
        return False
    if layer is not None and record.get("layer") != layer:
        return False
    return True


def _read_all_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _follow_records(path: Path, run_id: str | None, layer: str | None) -> None:
    if not path.exists():
        print(f"Trace file not found: {path}", file=sys.stderr)
        return

    with open(path, "r", encoding="utf-8") as f:
        # Seek to end to show only new records
        f.seek(0, 2)
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.1)
                continue
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if _match(record, run_id, layer):
                _print_record(record)
                sys.stdout.flush()


def cmd_trace(config: AgentConfig, args: argparse.Namespace) -> int:
    trace_path = Path(config.trace_file).expanduser()
    run_id: str | None = getattr(args, "run_id", None) or None
    layer: str | None = args.layer
    follow: bool = args.follow
    raw: bool = args.raw

    if follow:
        _follow_records(trace_path, run_id, layer)
        return 0

    records = _read_all_records(trace_path)
    if not records:
        print(f"No trace records found at {trace_path}", file=sys.stderr)
        return 1

    matched = [r for r in records if _match(r, run_id, layer)]

    if raw:
        for record in matched:
            print(json.dumps(record, ensure_ascii=False))
        return 0

    for record in matched:
        _print_record(record)

    return 0
