# TUI 客户端

TUI 用 [Textual](https://textual.textualize.io/) 框架实现，底层和 CLI 一样——`SocketClient` 连接守护进程，订阅事件——只是呈现层换成了交互式终端界面。

## CLI 和 TUI 共享 SocketClient，差异仅在渲染层

```
cmd_run                          SocketClient                          SocketServer
+ StdoutPrinter                  connect()                             kama-core daemon
  打印到 stdout                  send_command()        ──命令──→
        │                        on_event()        ←──事件推送──  IpcEventBroadcaster
        │                        run_event_loop()
        ↓                              ↑
   SocketClient ←──────────────────────┘
        ↑
        │
KamaTuiApp
+ RichLog / VerticalScroll
  渲染到终端 UI
```

共用同一套 IPC 代码；区别只在 `on_event()` 注册的 handler：
- CLI → `StdoutPrinter.handle`
- TUI → `KamaTuiApp._handle_event`

布局：顶部一行状态栏，剩余空间是可滚动的富文本日志区。

```
┌─────────────────────────┐  ← 状态栏（1 行）
│ ● connected 127.0.0.1:7437  │
├─────────────────────────┤
│ ▶ run 20260515-abc 总结 README.md │  ← RichLog（剩余空间，可滚动）
│ step 1 planning...          │
│   I'll read the README to get started. │
│   tool read_file {"path":"README.md"}  │
│   tool read_file ✓ 4ms      │
└─────────────────────────┘
```

## 连接逻辑

连接逻辑在 `_socket_loop()` 里，`while True` 驱动：连接失败等 2 秒重试，连接成功后订阅事件、等到断开，断开后再等 2 秒重试：

```python
# tui/app.py（节选）

async def _socket_loop(self) -> None:
    while True:
        client = SocketClient(self._host, self._port)
        try:
            await client.connect()
        except (ConnectionRefusedError, OSError):
            status.update("● not connected – retrying in 2s")
            await asyncio.sleep(2)
            continue

        status.update(f"● connected {self._host}:{self._port}")
        loop_task = asyncio.create_task(client.run_event_loop())
        client.on_event(lambda e: self._handle_event(e, log))

        try:
            await client.send_command("event.subscribe", {...})
            await loop_task   # 阻塞到连接断开
        finally:
            self._flush_tokens(log)
            await client.close()

        status.update("● disconnected – retrying in 2s")
        await asyncio.sleep(2)
```

这个循环以 Textual worker 的形式启动，而不是 `asyncio.create_task`：

```python
def on_mount(self) -> None:
    self.run_worker(self._socket_loop(), exclusive=True, name="socket")
```

Textual 的 `run_worker` 把协程集成在 Textual 自己的事件循环里，worker 协程直接调用 `log.write()` 或 `status.update()` 是安全的，不需要额外的线程同步机制。

## Token 缓冲

LLM 流式生成时，`llm.token` 事件密集出现，每个只有一两个字符。每个 token 单独调一次 `RichLog.write()` 会导致屏幕频繁闪烁。

解决方案：收到 `llm.token` 只追加到内部字符串，不写屏；等到下一个非 token 事件来时，先把积攒的内容整体写入一行：

```python
# tui/app.py（节选）

def _handle_event(self, event: dict[str, Any], log: RichLog) -> None:
    t = event.get("type", "")

    if t == "llm.token":
        self._token_buf += event.get("token", "")
        return   # 不写屏

    self._flush_tokens(log)   # 非 token 事件来了，先把缓冲区写出去

    if t == "run.started":
        log.write(f"[bold blue]▶ run[/bold blue] {event.get('run_id')} {event.get('goal')}")
    elif t == "run.finished":
        s = event.get("status", "")
        color = "green" if s == "success" else "red"
        log.write(f"[{color}]■ run[/{color}] {s} {event.get('steps')} steps")
    ...
```

用户看到的效果：LLM 生成的一整段文字显示为一行，工具调用和步骤边界各自成行，有层次感，不闪烁。
