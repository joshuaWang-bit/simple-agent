from __future__ import annotations

import asyncio
import sys
from typing import Any

from textual.app import App
from textual.containers import Vertical
from textual.widgets import RichLog, Static

from simple_agent.core.config import get_config
from simple_agent.core.transport.socket_client import SocketClient


class KamaTuiApp(App[None]):
    CSS = """
    Screen { align: center middle; }
    #status { height: 1; content-align: center middle; }
    #log { height: 1fr; }
    """

    def __init__(self, replay_run_id: str | None = None) -> None:
        super().__init__()
        config = get_config()
        self._host = config.host
        self._port = config.port
        self._replay_run_id = replay_run_id
        self._token_buf = ""

    def compose(self) -> Any:
        yield Static("● not connected", id="status")
        with Vertical():
            yield RichLog(id="log", highlight=True, markup=True)

    def on_mount(self) -> None:
        self.run_worker(self._socket_loop(), exclusive=True, name="socket")

    async def _socket_loop(self) -> None:
        while True:
            client = SocketClient(self._host, self._port)
            try:
                await client.connect()
            except (ConnectionRefusedError, OSError):
                self._update_status("● not connected – retrying in 2s")
                await asyncio.sleep(2)
                continue

            self._update_status(f"● connected {self._host}:{self._port}")
            log = self.query_one("#log", RichLog)
            loop_task = asyncio.create_task(client.run_event_loop())
            client.on_event(lambda e: self._handle_event(e, log))

            try:
                sub_params: dict[str, Any] = {
                    "topics": ["run.*", "step.*", "tool.*", "llm.*"],
                    "scope": "global",
                }
                if self._replay_run_id:
                    sub_params["replay_from_run"] = self._replay_run_id
                await client.send_command("event.subscribe", sub_params)
                await loop_task
            finally:
                self._flush_tokens(log)
                await client.close()

            self._update_status("● disconnected – retrying in 2s")
            await asyncio.sleep(2)

    def _update_status(self, text: str) -> None:
        try:
            status = self.query_one("#status", Static)
            status.update(text)
        except Exception:
            pass

    def _handle_event(self, event: dict[str, Any], log: RichLog) -> None:
        t = event.get("type", "")

        if t == "llm.token":
            self._token_buf += event.get("token", "")
            return

        self._flush_tokens(log)

        if t == "run.started":
            log.write(
                f"[bold blue]▶ run[/bold blue] {event.get('run_id')} {event.get('goal')}"
            )
        elif t == "run.finished":
            s = event.get("status", "")
            color = "green" if s == "success" else "red"
            steps = event.get("step_count", 0)
            log.write(f"[{color}]■ run[/{color}] {s} {steps} steps")
        elif t == "step.started":
            log.write(f"[dim]step {event.get('step')} planning...[/dim]")
        elif t == "step.finished":
            log.write(f"[dim]step {event.get('step')} done[/dim]")
        elif t == "tool.call_started":
            log.write(
                f"[yellow]tool {event.get('tool_name')} {event.get('input')}[/yellow]"
            )
        elif t == "tool.call_finished":
            elapsed = event.get("elapsed_ms", 0)
            log.write(f"[green]tool {event.get('tool_name')} ✓ {elapsed}ms[/green]")
        elif t == "llm.request":
            log.write(f"[dim]llm request {event.get('model')}[/dim]")
        else:
            log.write(str(event))

    def _flush_tokens(self, log: RichLog) -> None:
        if self._token_buf:
            log.write(self._token_buf)
            self._token_buf = ""


def main() -> None:
    replay = sys.argv[1] if len(sys.argv) > 1 else None
    app = KamaTuiApp(replay_run_id=replay)
    app.run()


if __name__ == "__main__":
    main()
