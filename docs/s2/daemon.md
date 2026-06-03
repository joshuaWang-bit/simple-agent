# 守护进程接管 agent.run

s1 的守护进程只有一个 handler：`core.ping`。s2 在 `CoreApp` 里新增了两个：`event.subscribe` 和 `agent.run`。

`CoreApp.__init__` 里建立了守护进程的"神经中枢"：

```python
# core/app.py（节选）

class CoreApp:
    def __init__(self) -> None:
        self._bus = EventBus()
        self._broadcaster = IpcEventBroadcaster()
        self._bus.subscribe(self._broadcaster.handle)   # broadcaster 挂到总线
        self._current_run_task: asyncio.Task[None] | None = None
```

这两行接线是整个 s2 的关键：`IpcEventBroadcaster` 作为 `EventBus` 的订阅者挂上去，和 s1 的 `EventWriter` 并列。之后 `AgentRunner` 发布任何事件，`EventWriter` 写文件，`broadcaster` 推网络，两件事同时发生：

```
bus.publish(event)
    ├── EventWriter.handle(event)          → 写入 events.jsonl
    └── IpcEventBroadcaster.handle(event)  → 推给所有 TCP 客户端
```

`AgentRunner` 和 `AgentLoop` 对外面有没有客户端连着完全无感知，它们只管向 bus 发布事件。

## EventBus 广播：同一个事件同时落盘 + 推网络

```
AgentRunner / AgentLoop 只依赖 EventBus，不知道有哪些订阅者

         EventBus.publish(LlmTokenEvent)
              /                    \
            1st                    2nd
            ↓                        ↓
    EventWriter.handle      IpcEventBroadcaster.handle
            ↓                        ↓
    events.jsonl            topic / scope 过滤
    每行立即 flush                  fnmatch 匹配
                                      ↓
                               TCP 写回
                               EventPushEnvelope
                                      ↓
                               CLI / TUI 客户端
```

## event.subscribe 命令

```python
# core/app.py（节选）

async def _subscribe_handler(self, params: dict[str, Any]) -> EventSubscribeResult:
    cmd = EventSubscribeCommand.model_validate(params)
    writer = get_connection_writer()   # 拿到当前连接的 TCP 写端

    replayed_count = 0
    if cmd.replay_from_run is not None:
        replayed_count = await self._replay_events(cmd.replay_from_run, writer, cmd.topics)

    sub_id = self._broadcaster.subscribe(writer, cmd.topics, cmd.scope)
    return EventSubscribeResult(subscription_id=sub_id, replayed_count=replayed_count)
```

这里有一个问题：`_subscribe_handler` 需要当前连接的 TCP `writer`，这样才能把这条连接注册到 broadcaster。但 `SocketServer` 的所有 handler 签名统一是 `async def handler(params: dict) -> Any`，没有 `writer` 参数。如果为了这一个 handler 改签名，`core.ping` 等所有 handler 都要跟着变，接口就不统一了。

解决方案是 `ContextVar`。Python asyncio 里，每个协程有自己的"上下文"，`ContextVar` 是这个上下文里的一个槽位——100 个连接同时在处理，每个协程读到的 `_writer_var` 是自己那条连接的 writer，互不干扰：

```python
# core/transport/socket_server.py（节选）

_writer_var: ContextVar[asyncio.StreamWriter] = ContextVar("_writer_var")

def get_connection_writer() -> asyncio.StreamWriter:
    return _writer_var.get()

# 在 _handle_line 里，调用 handler 之前：
_writer_var.set(writer)
result = await handler(req.params)   # handler 里调 get_connection_writer() 就能拿到 writer
```

## agent.run 命令

```python
# core/app.py（节选）

async def _agent_run_handler(self, params: dict[str, Any]) -> AgentRunResult:
    cmd = AgentRunCommand.model_validate(params)

    if self._current_run_task and not self._current_run_task.done():
        raise RuntimeError("a run is already in progress")

    run_id = new_run_id()
    runner = AgentRunner(self._config, bus=self._bus)
    self._current_run_task = asyncio.create_task(
        runner.run(cmd.goal, run_id=run_id)   # 后台运行，不等它完成
    )
    return AgentRunResult(run_id=run_id)      # 立刻返回
```

`asyncio.create_task()` 把协程"扔到后台"：当前代码不等它，继续往下跑。handler 立刻返回 `run_id` 给客户端，客户端知道任务已经开始，就可以等事件了。

`AgentRunner` 接受一个可选的 `bus` 参数——传入守护进程的全局 bus，agent 发布的事件就会流经 broadcaster，推给所有订阅客户端。不传 `bus` 时 AgentRunner 自己创建一个本地 bus，行为和 s1 一模一样，现有测试不受影响。

还有一个顺序上的细节：在 `AgentRunner.run()` 内部，`run.started` 是在初始化 LLM provider **之前**发布的：

```python
async with EventWriter(run_path / "events.jsonl") as writer:
    writer.subscribe(bus)
    await bus.publish(RunStartedEvent(...))   # 先推送给客户端

    provider = AnthropicProvider(...)         # 然后才初始化 LLM
    loop = AgentLoop(provider, registry, bus)
    await loop.run(context)
```

这样即使 LLM provider 初始化失败，客户端也已经收到了 `run.started`，而不是一直等待什么都不知道。
