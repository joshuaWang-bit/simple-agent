# SocketClient：一条连接，两种消息

`SocketClient` 是客户端侧的连接抽象。连接守护进程后，同一条 TCP 流上会出现两种消息：

- **命令响应**：JSON-RPC 2.0 格式，带 `"jsonrpc": "2.0"` 和 `"id"` 字段，对应之前发出的某个请求
- **事件推送**：带 `"kind": "event"` 字段，是守护进程主动发来的，没有 `id`

实际的流大概长这样：

```
# 两种消息混合出现在同一条 TCP 流里（按时间顺序）：

{"jsonrpc":"2.0","id":"req-1","result":{"subscription_id":"sub-abc","replayed_count":0}}
{"jsonrpc":"2.0","id":"req-2","result":{"run_id":"20260515-abc"}}
{"kind":"event","event":{"type":"run.started","run_id":"20260515-abc",...}}
{"kind":"event","event":{"type":"step.started","step":1,...}}
{"kind":"event","event":{"type":"llm.token","token":"I'll",...}}
{"kind":"event","event":{"type":"llm.token","token":" read",...}}
```

## 同一条 TCP 连接里的两类消息

```
SocketClient (kama / kama-tui)                    SocketServer (kama-core)

① 命令请求 + JSON-RPC 响应

  event.subscribe  ───────────────────────────────→  {"jsonrpc":"2.0","id":"req-1","result":{...}}
                       识别字段：jsonrpc + id

  agent.run        ───────────────────────────────→  {"jsonrpc":"2.0","id":"req-2","result":
                                                       {"run_id":"..."}}

② 事件推送（kind=event，无请求 id）

  on_event(handler) ←──────────────────────────────  {"kind":"event","event":{"type":"run.started",...}}
                       识别字段：kind = "event"         {"kind":"event","event":
                                                          {"type":"llm.token","token":"..."}}
```

为什么放在同一条连接里，而不是单独开一条连接专门推事件？分成两条连接需要管理两个生命周期，断开时要两边同步清理，还要有机制把两条连接绑定到同一个"会话"——实现更复杂，收益不明显。

## `_dispatch()` 路由器

`SocketClient._dispatch()` 是解析这个混合流的路由器：

```python
# core/transport/socket_client.py（节选）

async def _dispatch(self, line: bytes) -> None:
    msg = json.loads(line)

    if "jsonrpc" in msg:
        # 命令响应：找到等待它的 Future，完成它
        req_id = msg.get("id")
        if req_id and req_id in self._pending:
            fut = self._pending.pop(req_id)
            if "error" in msg:
                err = msg["error"]
                fut.set_exception(IpcError(err["code"], err["message"]))
            else:
                fut.set_result(msg.get("result") or {})

    elif msg.get("kind") == "event":
        # 事件推送：调用所有注册的事件处理器
        event_data = msg.get("event", {})
        for handler in self._event_handlers:
            await handler(event_data)
```

`_pending` 是一个字典，键是请求 ID，值是一个 `Future`。`send_command()` 发出请求之前，创建一个空的 `Future` 存进去，然后 `await fut` 挂起等待；等 `_dispatch()` 解析到对应 ID 的响应，调用 `fut.set_result()`，挂起的地方就被唤醒，拿到结果继续执行。这是 asyncio 里"等一个还没到的值"的标准做法。

`send_command()` 和 `run_event_loop()` 在同一个事件循环里并发运行：前者在等 Future 时不阻塞，后者持续读取服务器消息；读到命令响应，`_dispatch()` 完成 Future，`send_command()` 就被唤醒。两者通过 asyncio 的调度机制交替执行。
