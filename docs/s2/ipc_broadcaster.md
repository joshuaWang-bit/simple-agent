# IPC 事件广播

`IpcEventBroadcaster` 是 s2 的核心新模块。每次有客户端发 `event.subscribe`，它就记下这条连接的信息：

```python
# core/transport/ipc_broadcaster.py（节选）

@dataclass
class _Subscription:
    sub_id: str
    writer: asyncio.StreamWriter   # TCP 连接的写端
    topics: list[str]              # 如 ["run.*", "step.*", "llm.token"]
    scope: str                     # "global" 或 "run:<run_id>"
```

EventBus 发布事件时，`handle()` 被调用，遍历订阅列表，过滤 topic 和 scope，把匹配的事件推给对应客户端：

```python
# core/transport/ipc_broadcaster.py（节选）

async def handle(self, event: BaseModel) -> None:
    event_dict = event.model_dump()
    event_type = event_dict.get("type", "")
    run_id = event_dict.get("run_id")

    dead: list[asyncio.StreamWriter] = []

    for sub in list(self._subscriptions):
        if not self._matches_topic(event_type, sub.topics):
            continue
        if not self._matches_scope(run_id, sub.scope):
            continue
        try:
            envelope = EventPushEnvelope(event=event_dict)
            sub.writer.write(envelope.model_dump_json().encode() + b"\n")
            await sub.writer.drain()
        except (ConnectionResetError, BrokenPipeError, OSError):
            dead.append(sub.writer)   # 先记下，fan-out 完再清理

    for writer in dead:
        self.unsubscribe(writer)
```

Topic 过滤用 `fnmatch` —— `"step.*"` 匹配 `"step.started"` 和 `"step.finished"`，`"tool.*"` 匹配所有 tool 事件。客户端只会收到自己声明感兴趣的事件类型，不相关的过滤掉不发。

Scope 过滤：`"global"` 接收所有 run 的事件，`"run:<run_id>"` 只接收特定 run 的事件。CLI 用 `"global"`，这样它触发的那次 run 的事件能收到。

```python
@staticmethod
def _matches_scope(run_id: str | None, scope: str) -> bool:
    if scope == "global":
        return True
    if scope.startswith("run:"):
        return run_id == scope[4:]
    return False
```

死连接（客户端已断开但 broadcaster 还不知道）在推送时触发 `BrokenPipeError`。处理方式是先把出问题的 writer 记进 `dead` 列表，fan-out 全部完成后再统一清理——不能在遍历 `self._subscriptions` 的过程中修改它，否则会跳过某些订阅者。

## IpcEventBroadcaster 的过滤与广播流程

```
收到 event（来自 EventBus.publish）
        ↓
读取 event.type + run_id
        ↓
遍历订阅列表 (for sub in subscriptions)
        ↓
    topic 匹配?
    fnmatch(event.type, sub.topics)
        ↓ 是              否 → 跳过 (continue)
    scope 匹配?
    global 或 run:
        ↓ 是              否 → 跳过 (continue)
    写入 EventPushEnvelope
    writer.write(...) + drain()
        ↓
    成功 → 保留订阅    失败(BrokenPipeError) → 加入 dead 列表
        ↓
    fan-out 完成后统一 unsubscribe dead writers
```

遍历中不能修改列表，fan-out 完成后才统一清理。

客户端主动断开时，`SocketServer` 在连接处理函数的 `finally` 块里调用 `broadcaster.unsubscribe(writer)`，立刻清掉这条连接的订阅，不用等到下次推送失败才发现：

```python
# core/transport/socket_server.py（节选）

async def _handle_connection(self, reader, writer):
    try:
        await self._read_loop(reader, writer)
    finally:
        if self._broadcaster is not None:
            self._broadcaster.unsubscribe(writer)   # 断开时清理订阅
        writer.close()
```
