from __future__ import annotations

from typing import Any

from simple_agent.tui.app import KamaTuiApp, LLMStreamBlock, ToolCallBlock


class _AppendLog:
    def __init__(self, app: KamaTuiApp) -> None:
        self.widgets: list[Any] = []
        self._original = app._append
        app._append = self._capture  # type: ignore[method-assign]

    def _capture(self, widget: Any) -> None:
        self.widgets.append(widget)

    def text_lines(self) -> list[str]:
        lines: list[str] = []
        for w in self.widgets:
            if hasattr(w, "render"):
                lines.append(str(w.render()))
            else:
                lines.append(str(w))
        return lines


def test_handle_event_run_started() -> None:
    app = KamaTuiApp()
    log = _AppendLog(app)
    app._handle_event({"type": "run.started", "run_id": "r1", "goal": "test"})
    assert any("r1" in line and "test" in line for line in log.text_lines())


def test_handle_event_run_finished_success() -> None:
    app = KamaTuiApp()
    log = _AppendLog(app)
    app._handle_event(
        {"type": "run.finished", "run_id": "r1", "status": "success", "step_count": 3, "elapsed_s": 1.2},
    )
    assert any("success" in line for line in log.text_lines())


def test_handle_event_run_finished_failed() -> None:
    app = KamaTuiApp()
    log = _AppendLog(app)
    app._handle_event(
        {"type": "run.finished", "run_id": "r1", "status": "failed", "step_count": 1, "elapsed_s": 0.5},
    )
    assert any("failed" in line for line in log.text_lines())


def test_token_buffering() -> None:
    app = KamaTuiApp()
    log = _AppendLog(app)

    # Multiple llm.token events should accumulate in LLMStreamBlock
    app._handle_event({"type": "llm.token", "token": "Hello"})
    assert len(log.widgets) == 1
    assert isinstance(log.widgets[0], LLMStreamBlock)
    assert log.widgets[0]._text == "Hello"

    app._handle_event({"type": "llm.token", "token": " world"})
    assert len(log.widgets) == 1  # Same block reused
    assert log.widgets[0]._text == "Hello world"

    # A non-token event should finalize the current LLM block and create a new widget
    app._handle_event({"type": "step.started", "step": 1})
    assert len(log.widgets) == 2
    assert log.widgets[0]._finalized is True


def test_flush_tokens_on_run_finished() -> None:
    app = KamaTuiApp()
    log = _AppendLog(app)

    app._handle_event({"type": "llm.token", "token": "xyz"})
    assert len(log.widgets) == 1
    assert isinstance(log.widgets[0], LLMStreamBlock)

    app._handle_event(
        {"type": "run.finished", "run_id": "r1", "status": "success", "step_count": 2, "elapsed_s": 1.0},
    )
    assert len(log.widgets) == 2
    assert log.widgets[0]._finalized is True


def test_tool_call_block_lifecycle() -> None:
    app = KamaTuiApp()
    log = _AppendLog(app)

    app._handle_event({
        "type": "tool.call_started",
        "tool_use_id": "tc1",
        "tool_name": "bash",
        "input": {"command": "echo hello"},
    })
    assert len(log.widgets) == 1
    assert isinstance(log.widgets[0], ToolCallBlock)
    assert log.widgets[0]._finished is False

    app._handle_event({
        "type": "tool.call_finished",
        "tool_use_id": "tc1",
        "tool_name": "bash",
        "elapsed_ms": 15,
        "output": "hello",
    })
    assert log.widgets[0]._finished is True
    assert log.widgets[0]._output == "hello"
