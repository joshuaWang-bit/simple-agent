from __future__ import annotations

from typing import Any

from simple_agent.tui.app import KamaTuiApp


class _FakeLog:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write(self, text: str) -> None:
        self.lines.append(text)


def test_handle_event_run_started() -> None:
    app = KamaTuiApp()
    log = _FakeLog()
    app._handle_event({"type": "run.started", "run_id": "r1", "goal": "test"}, log)
    assert any("r1" in line and "test" in line for line in log.lines)


def test_handle_event_run_finished_success() -> None:
    app = KamaTuiApp()
    log = _FakeLog()
    app._handle_event(
        {"type": "run.finished", "run_id": "r1", "status": "success", "step_count": 3},
        log,
    )
    assert any("success" in line for line in log.lines)


def test_handle_event_run_finished_failed() -> None:
    app = KamaTuiApp()
    log = _FakeLog()
    app._handle_event(
        {"type": "run.finished", "run_id": "r1", "status": "failed", "step_count": 1},
        log,
    )
    assert any("failed" in line for line in log.lines)


def test_token_buffering() -> None:
    app = KamaTuiApp()
    log = _FakeLog()

    # Multiple llm.token events should be buffered
    app._handle_event({"type": "llm.token", "token": "Hello"}, log)
    assert len(log.lines) == 0  # Not written yet

    app._handle_event({"type": "llm.token", "token": " world"}, log)
    assert len(log.lines) == 0  # Still buffered

    # A non-token event should flush the buffer
    app._handle_event({"type": "step.started", "step": 1}, log)
    assert "Hello world" in log.lines[0]


def test_flush_tokens_on_run_finished() -> None:
    app = KamaTuiApp()
    log = _FakeLog()

    app._handle_event({"type": "llm.token", "token": "xyz"}, log)
    assert len(log.lines) == 0

    app._handle_event(
        {"type": "run.finished", "run_id": "r1", "status": "success", "step_count": 2},
        log,
    )
    assert "xyz" in log.lines[0]
