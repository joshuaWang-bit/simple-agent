from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from rich.markdown import Markdown
from textual.app import App
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static, TextArea

from simple_agent.core.config import get_config
from simple_agent.core.transport.socket_client import SocketClient


class LLMStreamBlock(Static):
    def __init__(self) -> None:
        super().__init__("")
        self._text = ""
        self._finalized = False

    def append_token(self, token: str) -> None:
        self._text += token
        self.update(self._text)

    def finalize_markdown(self) -> None:
        if self._finalized:
            return
        self._finalized = True
        if self._text.strip():
            self.update(Markdown(self._text, code_theme="monokai"))


class ToolCallBlock(Widget):
    DEFAULT_CSS = """
    ToolCallBlock {
        height: auto;
        padding: 0 2;
        color: $text-muted;
    }
    ToolCallBlock > .detail {
        display: none;
        padding: 0 2 0 4;
        color: $text-muted;
    }
    ToolCallBlock.expanded > .detail {
        display: block;
    }
    """

    def __init__(self, tool_name: str, input_data: dict[str, Any]) -> None:
        super().__init__()
        self._tool_name = tool_name
        self._input_data = input_data
        self._finished = False
        self._is_error = False
        self._elapsed_ms = 0
        self._output = ""
        self._params_full = json.dumps(input_data, indent=2, ensure_ascii=False)

    def compose(self) -> Any:
        yield Static(self._summary(), classes="summary")
        yield Static("", classes="detail")

    def mark_finished(self, elapsed_ms: int, output: str, is_error: bool = False) -> None:
        self._finished = True
        self._elapsed_ms = elapsed_ms
        self._output = output
        self._is_error = is_error
        try:
            summary = self.query_one(".summary", Static)
            summary.update(self._summary())
            if is_error:
                summary.styles.color = "red"
        except Exception:
            pass

    def on_click(self) -> None:
        if not self._finished:
            return
        if "expanded" in self.classes:
            self.remove_class("expanded")
        else:
            detail = self.query_one(".detail", Static)
            detail.update(
                f"[dim]params[/dim]\n{self._params_full}\n\n"
                f"[dim]output[/dim]\n{self._output}\n\n"
                f"[dim]elapsed:[/dim] {self._elapsed_ms}ms"
            )
            self.add_class("expanded")

    def _summary(self) -> str:
        parts: list[str] = []
        for k, v in self._input_data.items():
            sv = str(v)
            if len(sv) > 40:
                sv = sv[:37] + "..."
            parts.append(f"{k}={sv!r}")
        params_str = " ".join(parts)
        status = "error" if self._is_error else "done"
        return f"tool {self._tool_name} {params_str}  {status}  {self._elapsed_ms}ms (click to expand)"


class PermissionBlock(Static):
    def __init__(self, tool_use_id: str, tool_name: str, param_preview: str) -> None:
        super().__init__("")
        self._tool_use_id = tool_use_id
        self._tool_name = tool_name
        self._param_preview = param_preview
        self._decision: str | None = None

    def render(self) -> Any:
        from rich.text import Text

        if self._decision is None:
            return Text.from_markup(
                f"[yellow]⏸ permission[/yellow] {self._tool_name} {self._param_preview}"
            )
        color = "green" if self._decision in ("allow_once", "always_allow") else "red"
        return Text.from_markup(
            f"[{color}]permission {self._decision}[/{color}] {self._tool_name} {self._param_preview}"
        )

    def mark_decision(self, decision: str) -> None:
        self._decision = decision
        self.refresh()


class PermissionSelect(Widget):
    can_focus = True

    DEFAULT_CSS = """
    PermissionSelect {
        height: auto;
        padding: 0 2;
    }
    PermissionSelect > .option {
        padding: 0 1;
    }
    PermissionSelect > .option.highlighted {
        background: $accent;
        color: $text;
        text-style: bold;
    }
    """

    def __init__(self, tool_use_id: str) -> None:
        super().__init__()
        self._tool_use_id = tool_use_id
        self._options = [
            ("allow_once", "Allow once (y)"),
            ("always_allow", "Always allow (a)"),
            ("deny_once", "Deny once (n)"),
            ("always_deny", "Always deny (d)"),
        ]
        self._index = 0

    def compose(self) -> Any:
        for value, label in self._options:
            yield Static(label, classes=f"option opt-{value}")

    def on_mount(self) -> None:
        self._update_highlight()

    def _update_highlight(self) -> None:
        for i, static in enumerate(self.query(".option")):
            if i == self._index:
                static.add_class("highlighted")
            else:
                static.remove_class("highlighted")
        self.focus()

    async def on_key(self, event: Any) -> None:
        key = event.key
        if key in ("up", "k"):
            self._index = (self._index - 1) % len(self._options)
            self._update_highlight()
            event.stop()
        elif key in ("down", "j"):
            self._index = (self._index + 1) % len(self._options)
            self._update_highlight()
            event.stop()
        elif key == "enter":
            decision = self._options[self._index][0]
            await self._send_decision(decision)
            event.stop()
        elif key == "y":
            await self._send_decision("allow_once")
            event.stop()
        elif key == "a":
            await self._send_decision("always_allow")
            event.stop()
        elif key == "n":
            await self._send_decision("deny_once")
            event.stop()
        elif key == "d":
            await self._send_decision("always_deny")
            event.stop()

    async def _send_decision(self, decision: str) -> None:
        app = self.app
        if isinstance(app, KamaTuiApp) and app._client:
            perm_block = app._pending_permission_blocks.get(self._tool_use_id)
            if perm_block is not None:
                perm_block.mark_decision(decision)
            app.run_worker(
                self._do_send(decision),
                name="permission_respond",
                exclusive=False,
            )
        self.remove()

    async def _do_send(self, decision: str) -> None:
        app = self.app
        if isinstance(app, KamaTuiApp) and app._client:
            await app._client.send_command("permission.respond", {
                "tool_use_id": self._tool_use_id,
                "decision": decision,
            })


class ChatTextArea(TextArea):
    class Submitted(Message):
        def __init__(self, area: ChatTextArea) -> None:
            self.text_area = area
            self.value = area.text
            super().__init__()

    async def _on_key(self, event: Any) -> None:
        key = event.key
        if key == "enter":
            event.stop()
            event.prevent_default()
            if self.text.strip():
                self.post_message(self.Submitted(self))
            return
        if key in ("alt+enter", "shift+enter", "ctrl+j", "super+enter"):
            event.stop()
            event.prevent_default()
            if not self.read_only:
                self.insert("\n")
            return
        await super()._on_key(event)


class KamaTuiApp(App[None]):
    CSS = """
    Screen { align: center middle; }
    #status { height: 1; content-align: center middle; dock: top; }
    #scroll { width: 100%; height: 1fr; }
    #input { height: 3; dock: bottom; }
    """

    def __init__(self, replay_run_id: str | None = None) -> None:
        super().__init__()
        config = get_config()
        self._host = config.host
        self._port = config.port
        self._replay_run_id = replay_run_id
        self._current_llm: LLMStreamBlock | None = None
        self._tools: dict[str, ToolCallBlock] = {}
        self._session_id: str | None = None
        self._client: SocketClient | None = None
        self._pending_permission_blocks: dict[str, PermissionBlock] = {}

    def compose(self) -> Any:
        yield Static("● not connected", id="status")
        yield VerticalScroll(id="scroll")
        yield ChatTextArea(id="input", disabled=True)

    def on_mount(self) -> None:
        self.run_worker(self._socket_loop(), exclusive=True, name="socket")

    def _append(self, widget: Widget) -> None:
        scroll = self.query_one("#scroll", VerticalScroll)
        scroll.mount(widget)
        scroll.scroll_end(animate=False)

    def _break_llm(self) -> None:
        if self._current_llm is not None:
            self._current_llm.finalize_markdown()
            self._current_llm = None

    def _set_input_disabled(self, disabled: bool) -> None:
        try:
            inp = self.query_one("#input", ChatTextArea)
            inp.disabled = disabled
        except Exception:
            pass

    async def _socket_loop(self) -> None:
        while True:
            client = SocketClient(self._host, self._port)
            try:
                await client.connect()
            except (ConnectionRefusedError, OSError):
                self._update_status("● not connected – retrying in 2s")
                await asyncio.sleep(2)
                continue

            self._client = client
            self._update_status(f"● connected {self._host}:{self._port}")
            loop_task = asyncio.create_task(client.run_event_loop())
            async def on_event(event: dict[str, Any]) -> None:
                self._handle_event(event)

            client.on_event(on_event)

            try:
                sub_params: dict[str, Any] = {
                    "topics": ["session.*", "run.*", "step.*", "tool.*", "llm.*", "permission.*"],
                    "scope": "global",
                }
                if self._replay_run_id:
                    sub_params["replay_from_run"] = self._replay_run_id
                await client.send_command("event.subscribe", sub_params)
                created = await client.send_command("session.create", {"mode": "chat"})
                self._session_id = str(created["session_id"])
                self._set_input_disabled(False)
                await loop_task
            finally:
                self._break_llm()
                self._set_input_disabled(True)
                await client.close()
                self._client = None

            self._update_status("● disconnected – retrying in 2s")
            await asyncio.sleep(2)

    def _update_status(self, text: str) -> None:
        try:
            status = self.query_one("#status", Static)
            status.update(text)
        except Exception:
            pass

    def _handle_event(self, event: dict[str, Any]) -> None:
        t = event.get("type", "")

        if t == "session.waiting_for_input":
            self._set_input_disabled(False)
            return

        if t == "llm.token":
            token = event.get("token", "")
            if self._current_llm is None:
                llm_block = LLMStreamBlock()
                self._append(llm_block)
                self._current_llm = llm_block
            self._current_llm.append_token(token)
            return

        self._break_llm()

        if t == "run.started":
            self._set_input_disabled(True)
            self._append(
                Static(
                    f"[bold blue]▶ run[/bold blue] {event.get('run_id')} {event.get('goal')}"
                )
            )
        elif t == "run.finished":
            s = event.get("status", "")
            color = "green" if s == "success" else "red"
            steps = event.get("step_count", 0)
            elapsed = event.get("elapsed_s", 0.0)
            self._append(
                Static(f"[{color}]■ run[/{color}] {s} {steps} steps {elapsed:.1f}s")
            )
        elif t == "step.started":
            self._append(Static(f"[dim]step {event.get('step')} planning...[/dim]"))
        elif t == "step.finished":
            self._append(Static(f"[dim]step {event.get('step')} done[/dim]"))
        elif t == "tool.call_started":
            tool_id = event.get("tool_use_id", "")
            tool_name = event.get("tool_name", "")
            input_data = event.get("input", {})
            block = ToolCallBlock(tool_name, input_data)
            self._tools[tool_id] = block
            self._append(block)
        elif t == "tool.call_finished":
            tool_id = event.get("tool_use_id", "")
            block = self._tools.pop(tool_id, None)
            if block is not None:
                block.mark_finished(
                    elapsed_ms=event.get("elapsed_ms", 0),
                    output=event.get("output", ""),
                    is_error=event.get("is_error", False),
                )
        elif t == "llm.request":
            self._append(Static(f"[dim]llm request {event.get('model')}[/dim]"))
        elif t == "permission.requested":
            tool_use_id = event.get("tool_use_id", "")
            tool_name = event.get("tool_name", "")
            preview = event.get("param_preview", "")
            perm_block = PermissionBlock(tool_use_id, tool_name, preview)
            self._pending_permission_blocks[tool_use_id] = perm_block
            self._append(perm_block)
            select = PermissionSelect(tool_use_id)
            self._mount_permission_select(select)
        else:
            self._append(Static(str(event)))

    def _mount_permission_select(self, select: PermissionSelect) -> None:
        scroll = self.query_one("#scroll", VerticalScroll)
        scroll.mount(select)
        scroll.scroll_end(animate=False)
        select.focus()

    async def _do_send_message(self, content: str) -> None:
        if not self._client or not self._session_id:
            return
        try:
            await self._client.send_command("session.send_message", {
                "session_id": self._session_id,
                "content": content,
            })
        except Exception as exc:
            self._append(Static(f"[red]error: {exc}[/red]"))
            self._set_input_disabled(False)

    def on_chat_text_area_submitted(self, message: ChatTextArea.Submitted) -> None:
        if not self._client or not self._session_id:
            return
        value = message.value.strip()
        if not value:
            return
        try:
            inp = self.query_one("#input", ChatTextArea)
            inp.text = ""
            inp.disabled = True
        except Exception:
            pass
        self._append(Static(f"[bold]You:[/bold] {value}"))
        self.run_worker(
            self._do_send_message(value),
            name="send_message",
            exclusive=False,
        )


def main() -> None:
    replay = sys.argv[1] if len(sys.argv) > 1 else None
    app = KamaTuiApp(replay_run_id=replay)
    app.run()


if __name__ == "__main__":
    main()
