# CLI 只负责发命令和消费事件

s1 的 `cmd_run` 直接调用 `asyncio.run(runner.run(goal))`，agent 就在这个进程里跑。s2 的 `cmd_run` 改成了通过网络触发：

```python
# cli/commands/run.py（节选）

async def _run_async(goal: str, config: KamaConfig) -> int:
    client = SocketClient(config.host, config.port)
    try:
        await client.connect()
    except (ConnectionRefusedError, OSError):
        print(f"error: core not running ({config.host}:{config.port})", file=sys.stderr)
        return 1

    printer = StdoutPrinter()
    finished = asyncio.Event()
    exit_code = 0

    async def on_event(event: dict[str, Any]) -> None:
        nonlocal exit_code
        await printer.handle(event)
        if event.get("type") == "run.finished":
            exit_code = 0 if event.get("status") == "success" else 1
            finished.set()

    client.on_event(on_event)
    loop_task = asyncio.create_task(client.run_event_loop())

    await client.send_command("event.subscribe", {
        "topics": ["run.*", "step.*", "tool.*", "llm.token", "llm.usage"],
        "scope": "global",
    })
    await client.send_command("agent.run", {"goal": goal})
    await finished.wait()
    ...
```

`AgentRunner` 消失了，换成了 `SocketClient`。`StdoutPrinter` 还在，但现在处理的是 `dict`，而不是 s1 里的 pydantic Event 对象——事件经过网络传输之后被反序列化为普通 Python 字典。

`asyncio.Event()` 是 asyncio 里的信号量：`finished.set()` 把它置位，`await finished.wait()` 会阻塞到置位为止。这里用来等 `run.finished` 事件：收到了就置位，`_run_async` 就能退出。

**顺序很关键**：`event.subscribe` 必须在 `agent.run` 之前发送。如果先发 `agent.run`，守护进程立刻开始跑，`run.started` 可能在你登记订阅之前就已经推出去了，客户端会错过。先订阅再触发，不丢第一个事件。
