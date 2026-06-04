from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from simple_agent.core.trace.record import TraceRecord, _now
from simple_agent.core.trace.writer import TraceWriter


# Unicode arrow character used in direction fields
_ARR = "\u2192"


@pytest.fixture
def temp_trace_path(tmp_path: Path) -> Path:
    return tmp_path / "traces" / "daemon.jsonl"


@pytest.mark.asyncio
async def test_emit_and_drain(temp_trace_path: Path) -> None:
    writer = TraceWriter(temp_trace_path)
    await writer.start()

    record = TraceRecord(
        ts=_now(),
        direction=f"CLIENT{_ARR}CORE",
        layer="ipc",
        kind="command",
        data={"method": "core.ping"},
    )
    writer.emit(record)

    # Give drain task time to write
    await asyncio.sleep(0.05)

    await writer.stop()

    lines = temp_trace_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["direction"] == f"CLIENT{_ARR}CORE"
    assert parsed["layer"] == "ipc"
    assert parsed["kind"] == "command"
    assert parsed["data"]["method"] == "core.ping"


@pytest.mark.asyncio
async def test_multiple_records_in_order(temp_trace_path: Path) -> None:
    writer = TraceWriter(temp_trace_path)
    await writer.start()

    for i in range(5):
        writer.emit(
            TraceRecord(
                ts=_now(),
                direction="CORE",
                layer="event",
                kind="event",
                data={"seq": i},
            )
        )

    await asyncio.sleep(0.05)
    await writer.stop()

    lines = temp_trace_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 5
    for i, line in enumerate(lines):
        parsed = json.loads(line)
        assert parsed["data"]["seq"] == i


@pytest.mark.asyncio
async def test_stop_waits_for_queue_drain(temp_trace_path: Path) -> None:
    writer = TraceWriter(temp_trace_path)
    await writer.start()

    # Emit many records without waiting between them
    for i in range(100):
        writer.emit(
            TraceRecord(
                ts=_now(),
                direction=f"CORE{_ARR}LLM",
                layer="llm",
                kind="api_call",
                data={"index": i},
            )
        )

    # stop() should wait until all are written
    await writer.stop()

    lines = temp_trace_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 100


@pytest.mark.asyncio
async def test_emit_is_non_blocking(temp_trace_path: Path) -> None:
    writer = TraceWriter(temp_trace_path)
    await writer.start()

    # emit() should return immediately without awaiting
    start = asyncio.get_event_loop().time()
    for _ in range(10):
        writer.emit(
            TraceRecord(
                ts=_now(),
                direction=f"CLIENT{_ARR}CORE",
                layer="ipc",
                kind="command",
                data={},
            )
        )
    elapsed = asyncio.get_event_loop().time() - start

    # Should be very fast (< 10ms for 10 calls) since it's just queue.put_nowait
    assert elapsed < 0.01

    await writer.stop()


@pytest.mark.asyncio
async def test_file_is_appended_not_overwritten(temp_trace_path: Path) -> None:
    writer1 = TraceWriter(temp_trace_path)
    await writer1.start()
    writer1.emit(
        TraceRecord(
            ts=_now(),
            direction=f"CLIENT{_ARR}CORE",
            layer="ipc",
            kind="command",
            data={"batch": 1},
        )
    )
    await asyncio.sleep(0.05)
    await writer1.stop()

    writer2 = TraceWriter(temp_trace_path)
    await writer2.start()
    writer2.emit(
        TraceRecord(
            ts=_now(),
            direction=f"CLIENT{_ARR}CORE",
            layer="ipc",
            kind="command",
            data={"batch": 2},
        )
    )
    await asyncio.sleep(0.05)
    await writer2.stop()

    lines = temp_trace_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["data"]["batch"] == 1
    assert json.loads(lines[1])["data"]["batch"] == 2
