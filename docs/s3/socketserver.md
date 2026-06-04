# 埋点 ①：IPC 层——SocketServer

SocketServer 在两个地方埋点：收到命令时，以及发出响应时。

## 收到命令（`_handle_line`，解析成功之后）

```python
# core/transport/socket_server.py（节选）

if self._trace is not None:
    client_id = str(writer.get_extra_info("peername", "<unknown>"))
    self._trace.emit(
        TraceRecord(
            ts=_now(),
            direction="CLIENT→CORE",
            layer="ipc",
            kind="command",
            client_id=client_id,
            data={"method": req.method, "id": req.id, "params": req.params},
        )
    )
```

埋点在 `JsonRpcRequest.model_validate(raw)` 成功之后——只记录合法的请求，解析失败的直接发错误响应，不写 trace（它们不属于"命令"，属于客户端 bug）。

## 发出响应（`_send`，`drain()` 之后）

```python
async def _send(self, writer: asyncio.StreamWriter, msg: BaseModel) -> None:
    writer.write(msg.model_dump_json().encode() + b"\n")
    await writer.drain()
    if self._trace is not None:
        kind = "error" if isinstance(msg, JsonRpcError) else "response"
        ...
        self._trace.emit(TraceRecord(direction="CORE→CLIENT", kind=kind, ...))
```

注意顺序：先 `drain()` 成功，再写 trace。这保证了 trace 里出现 `CORE→CLIENT` response 就意味着客户端确实收到了响应，不是"即将发送"。
