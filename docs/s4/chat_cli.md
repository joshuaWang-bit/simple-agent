# `sagent chat`：session 协议的 CLI 参考实现

TUI 输入框背后走的协议和 `sagent chat` 完全相同。先看 `sagent chat` 的实现，它更简洁，能让 session 协议的脉络看得更清楚。

s2 和 s3 的 `sagent run` 是一次性命令：发 goal，等 `run.finished`，然后退出。`sagent chat` 不退出，它反复做三件事：

1. 读用户输入
2. 发给 daemon
3. 打印 daemon 推回来的事件

入口在 `src/simple_agent/cli/commands/chat.py`：

```python
# src/simple_agent/cli/commands/chat.py（节选）

async def _chat_async(config: SagentConfig) -> int:
    client = SocketClient(config.host, config.port)
    await client.connect()

    printer = ChatPrinter()
    client.on_event(printer.handle)
    loop_task = asyncio.create_task(client.run_event_loop())

    await client.send_command("event.subscribe", {
        "topics": ["session.*", "run.*", "step.*", "tool.*", "llm.*"],
    })
    created = await client.send_command("session.create", {"mode": "chat"})
    session_id = str(created["session_id"])
    print(f"[session: {session_id}]")

    while True:
        line = await _readline("> ")
        if not line.strip():
            continue
        await client.send_command("session.send_message", {
            "session_id": session_id,
            "content": line,
        })
```

这里沿用了 s2 的 `SocketClient`：一条 TCP 连接上既发命令，也收事件。不同的是，`sagent chat` 先发 `session.create`，拿到一个 `session_id`，后续每条用户输入都发 `session.send_message`。TUI 启动时做的是完全一样的事，只是把 `input()` 换成了底部输入框。

注意顺序：**先订阅事件，再创建 session**。如果反过来，daemon 可能已经广播了 `session.created`，客户端才开始订阅，第一条事件就丢了。s2 里 `sagent run` 已经有这个经验：先 `event.subscribe`，再触发真正的动作。

还有一个小但关键的细节：读 stdin 不能直接 `input()`。

```python
async def _readline(prompt: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, input, prompt)
```

`input()` 是阻塞调用。如果直接在 async 函数里调用它，整个事件循环会停住；用户还没敲完下一句话时，daemon 推过来的 `llm.token` 也打印不出来。把 `input` 放到 executor 线程里，主事件循环就能继续收事件，终端才能一边等待输入、一边流式输出。

`ChatPrinter` 做的事情很少：收到 `llm.token` 就内联打印，收到 `tool.call_started` 就换行打印工具调用，收到 `session.waiting_for_input` 就提示 `[waiting for input]`。它不保存任何会话状态。

> 💡 两个客户端都只是"眼睛和耳朵"。真正的 session 状态、thread、notes、run 调度都在 daemon 里。TUI 和 CLI 共享完全相同的协议，不各自维护状态。
