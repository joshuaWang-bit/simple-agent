# S0 协议与传输层

## 传输层：TCP + NDJSON

SimpleAgent 的进程间通信采用 **NDJSON（Newline Delimited JSON）** over TCP：

- 每一条消息是一行完整的 JSON（以 `\n` 结尾）
- 服务端用 `reader.readline()` 读取，天然解决粘包问题
- 最大单行限制 1 MB，防止内存爆炸

这种格式的好处是**极度简单**——你可以直接用 `nc` 或 `telnet` 手动发请求调试：

```bash
$ nc 127.0.0.1 7437
{"jsonrpc":"2.0","id":"hand-1","method":"core.ping","params":{"client":"nc"}}
{"jsonrpc":"2.0","id":"hand-1","result":{"server_version":"0.0.1","uptime_ms":42,"received_at":"2026-06-02T09:21:56"}}
```

## 信封协议：JSON-RPC 2.0

在 NDJSON 之上，我们使用 JSON-RPC 2.0 作为信封格式：

### 请求格式

```json
{
  "jsonrpc": "2.0",
  "id": "cli-1",
  "method": "core.ping",
  "params": {"client": "cli/0.0.1"}
}
```

### 成功响应格式

```json
{
  "jsonrpc": "2.0",
  "id": "cli-1",
  "result": {
    "server_version": "0.0.1",
    "uptime_ms": 150,
    "received_at": "2026-06-02T09:21:56.748576+00:00"
  }
}
```

### 错误响应格式

```json
{
  "jsonrpc": "2.0",
  "id": "cli-1",
  "error": {
    "code": -32601,
    "message": "Method not found: core.unknown",
    "data": null
  }
}
```

> 注：`id` 用于请求和响应的对应。当前实现中 CLI 使用固定 `"cli-1"`，后续可改为自增或 UUID。

## CLI 侧的发送流程

进入 `cmd_ping` 后，我们从**同步 CLI 世界切到异步网络 I/O**：

```python
# cli/commands/ping.py
def cmd_ping(config: AgentConfig) -> None:
    try:
        asyncio.run(_ping(config))
    except (ConnectionRefusedError, OSError):
        print(f"error: core not running ({config.host}:{config.port})", file=sys.stderr)
        sys.exit(1)
```

`asyncio.run()` 启动事件循环，执行真正的 `_ping` 协程。s0 里只有一次请求，看起来同步也能写，但 daemon 侧一定是异步的；**CLI 从第一天就用同一种 I/O 模型**，后面扩展到事件订阅时不用换写法。

`_ping` 做的事情很直白：**连接、写一行、读一行、解析响应**。

```python
async def _ping(config: AgentConfig) -> None:
    t0 = time.monotonic()
    reader, writer = await asyncio.open_connection(config.host, config.port)

    req = {
        "jsonrpc": "2.0",
        "id": "cli-1",
        "method": "core.ping",
        "params": {"client": f"cli/{__version__}"},
    }
    writer.write((json.dumps(req) + "\n").encode())
    await writer.drain()

    line = await asyncio.wait_for(reader.readline(), timeout=10.0)
    latency_ms = int((time.monotonic() - t0) * 1000)

    raw = json.loads(line)
    if "error" in raw:
        err = JsonRpcError.model_validate(raw)
        print(f"error: {err.error.code} {err.error.message}", file=sys.stderr)
        sys.exit(1)

    resp = JsonRpcSuccess.model_validate(raw)
    result = PongResult.model_validate(resp.result)
    print(f"pong server={result.server_version} uptime={result.uptime_ms}ms latency={latency_ms}ms")

    raw = json.loads(line)
    if "error" in raw:
        err = JsonRpcError.model_validate(raw)
        print(f"error: {err.error.code} {err.error.message}", file=sys.stderr)
        sys.exit(1)

    resp = JsonRpcSuccess.model_validate(raw)
    result = PongResult.model_validate(resp.result)
    print(f"pong server={result.server_version} uptime={result.uptime_ms}ms latency={latency_ms}ms")

    writer.close()
    await writer.wait_closed()
```

### CLI 解析响应并打印结果

回到 CLI。`reader.readline()` 拿到 daemon 写回的一行 JSON 后，先判断它是错误还是成功：

```python
raw = json.loads(line)
if "error" in raw:
    err = JsonRpcError.model_validate(raw)
    print(f"error: {err.error.code} {err.error.message}", file=sys.stderr)
    sys.exit(1)

resp = JsonRpcSuccess.model_validate(raw)
result = PongResult.model_validate(resp.result)
print(f"pong server={result.server_version} uptime={result.uptime_ms}ms latency={latency_ms}ms")
```

这里没有直接 `print(raw["result"])`，而是把响应再次验证成 `JsonRpcSuccess` 和 `PongResult`。原因和 daemon 侧一样：**IPC 两端都应该把边界数据当成不可信输入**。daemon 写错响应、版本不匹配、字段缺失，都应该在边界处暴露出来。

`latency_ms` 是 CLI 自己测的往返耗时，`uptime_ms` 是 daemon 自己报告的运行时长。两个字段来源不同，刚好能证明**这不是一个本地假输出，而是真正走了一次跨进程请求/响应**。

### 为什么选这两层协议？

这里同时确定了两层协议。

**第一层是 JSON-RPC 2.0。** `method` 表示要调用的能力，`params` 放参数，`id` 用来让响应和请求对应。s0 的 CLI 一次只发一个请求，暂时还感受不到 `id` 的价值；但 S2 之后 TUI 可能在同一条连接上同时发多个命令，到那时 `id` 就是区分响应归属的关键。

**第二层是 NDJSON。** 每条消息是一行 JSON，以 `\n` 结尾。这样 daemon 可以直接用 `StreamReader.readline()` 定界，不需要自己维护半包、粘包和长度字段。

> 💡 没有选择"直接发一个 dict 字符串"或"自定义一个很轻的协议"，是因为 IPC 边界上的错误会非常难查。JSON-RPC 至少把成功、失败、请求 ID、方法名这些结构固定下来；NDJSON 则让每帧消息能被日志工具、`nc`、`tail` 直接读懂。

## 协议模型先挡住坏消息

CLI 发出去的是 JSON，但 daemon **不能直接相信这份 JSON**。进程间传递的消息必须先经过协议模型验证。

### 信封：`core/bus/envelope.py`

定义 JSON-RPC 外壳：

```python
class JsonRpcRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str
    method: str
    params: dict[str, Any] = {}

class JsonRpcSuccess(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str
    result: Any

class JsonRpcError(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | None = None
    error: JsonRpcErrorObject
```

错误码常量：

```python
PARSE_ERROR      = -32700
INVALID_REQUEST  = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS   = -32602
INTERNAL_ERROR   = -32603
```

### 业务模型：`core/bus/commands.py`

定义业务命令和结果。s0 只有一个真正的命令：

```python
class PingCommand(BaseModel):
    type: Literal["core.ping"] = "core.ping"
    client: str

class PongResult(BaseModel):
    server_version: str
    uptime_ms: int
    received_at: str

Command = Annotated[
    PingCommand,
    Discriminator("type"),
]
```

### 为什么有 method 还要有 type？

你可能会问：JSON-RPC 已经有 `method: "core.ping"` 了，为什么 `PingCommand` 里还要有 `type: "core.ping"`？

因为这是**两层边界**：

- **`method`** 是 **RPC 路由字段**，负责把请求送到哪个 handler；
- **`type`** 是 **业务 payload 的判别字段**，负责让 pydantic 知道 `params` 应该按哪个模型解析。

现在只有 `PingCommand`，差别不大；等后续阶段有 `agent.run`、`event.subscribe`、`session.send_message` 时，discriminated union 会让"按 type 解析成具体模型"这件事保持统一。

> 💡 在 IPC 边界用 pydantic 模型，不是为了写更多类，而是为了让坏消息尽早失败。字段名拼错、类型不对、未知 method，都应该变成明确的 JSON-RPC 错误，而不是在业务代码深处变成 `KeyError` 或静默丢失。

## daemon 监听 TCP 并并行处理

现在看 daemon 这一侧。`sagent-core` 的入口在 `core/app.py`，它加载配置、初始化日志、创建 `SocketServer`，然后注册 `core.ping`：

```python
# core/app.py (s0 关键路径)
class CoreApp:
    async def run(self) -> None:
        self._start_time = time.monotonic()
        config = get_config()
        setup_logging(config)

        server = SocketServer(config.host, config.port)
        server.register("core.ping", self._ping_handler)

        addr = await server.start()
        logger.info("sagent-core %s listening addr=%s", __version__, addr)

        shutdown = asyncio.Event()
        loop = asyncio.get_running_loop()
        if sys.platform == "win32":
            signal.signal(signal.SIGINT, lambda _s, _f: shutdown.set())
        else:
            loop.add_signal_handler(signal.SIGINT, shutdown.set)
            loop.add_signal_handler(signal.SIGTERM, shutdown.set)

        await shutdown.wait()
        await server.stop()
```

### 端口探活

`SocketServer.start()` 启动监听前会先探活一次：

```python
async def start(self) -> str:
    try:
        _r, w = await asyncio.open_connection(self._host, self._port)
        w.close()
        await w.wait_closed()
        raise SystemExit(f"core already running at {self._host}:{self._port}")
    except (ConnectionRefusedError, OSError):
        pass

    self._server = await asyncio.start_server(
        self._handle_connection,
        host=self._host,
        port=self._port,
        limit=_MAX_LINE_BYTES,
    )
    return f"{self._host}:{self._port}"
```

如果目标地址已经能连上，就说明已有 daemon 在跑，直接退出。否则再调用 `asyncio.start_server()` 绑定端口。**这里没有引入 pid 文件**，因为 s0 用的是 TCP loopback：**端口本身就是最可靠的占用状态**。

### 读循环

每个客户端连接进来后，server 持续 `readline()`：

```python
async def _read_loop(
    self,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    while True:
        line = await reader.readline()
        if not line:
            return
        await self._handle_line(line, writer)
```

`limit=_MAX_LINE_BYTES` 把单行帧限制在 1 MB，防止一个异常客户端发出超大行把内存顶爆。s0 的 `ping` 很小，但**传输层从第一天就应该有边界**。

### 完整的请求处理生命周期

`SocketServer` 实现了完整的请求处理生命周期：

1. **端口探活**：启动前尝试连接目标端口，若成功则说明已有 daemon 在跑，直接退出
2. **连接管理**：每个 TCP 连接独立一个 `_handle_connection` 协程，连接断开时自动清理
3. **读循环**：持续 `readline()`，直到对端关闭连接（收到空 bytes）
4. **处理单行**：
   - `json.loads()` 失败 → `PARSE_ERROR`
   - Pydantic 验证失败 → `INVALID_REQUEST`
   - method 找不到 → `METHOD_NOT_FOUND`
   - handler 抛 `ValidationError` → `INVALID_PARAMS`
   - handler 抛其他异常 → `INTERNAL_ERROR`
5. **写回响应**：无论成功或错误，都把 JSON-RPC 响应写回客户端

### 一行请求如何变成 PongResult

`_handle_line` 是整条 ping 路径的核心。它把字节流一步步变成 handler 返回值：

```python
async def _handle_line(self, line: bytes, writer: asyncio.StreamWriter) -> None:
    try:
        raw = json.loads(line)
    except json.JSONDecodeError as e:
        await self._send(writer, make_error(None, PARSE_ERROR, f"Parse error: {e}"))
        return

    try:
        req = JsonRpcRequest.model_validate(raw)
    except ValidationError as e:
        await self._send(writer, make_error(None, INVALID_REQUEST, "Invalid Request", str(e)))
        return

    handler = self._handlers.get(req.method)
    if handler is None:
        await self._send(
            writer,
            make_error(req.id, METHOD_NOT_FOUND, f"Method not found: {req.method}"),
        )
        return

    try:
        result = await handler(req.params)
    except ValidationError as e:
        await self._send(writer, make_error(req.id, INVALID_PARAMS, "Invalid params", str(e)))
        return
    except Exception:
        logger.exception("Handler error for %s", req.method)
        await self._send(writer, make_error(req.id, INTERNAL_ERROR, "Internal error"))
        return

    await self._send(writer, JsonRpcSuccess(id=req.id, result=result.model_dump()))
```

这段代码有一个重要特征：**每一种失败都有结构化响应**。

非法 JSON 返回 `-32700`，JSON-RPC 外壳不对返回 `-32600`，未知 method 返回 `-32601`，参数验证失败返回 `-32602`，handler 自己崩了返回 `-32603`。客户端不会遇到"连接突然断了但不知道发生什么"的状态。

### 真正的 `core.ping` handler

```python
async def _ping_handler(self, params: dict[str, Any]) -> PongResult:
    cmd = PingCommand.model_validate(params)
    logger.debug("ping from %s", cmd.client)
    return PongResult(
        server_version=__version__,
        uptime_ms=int((time.monotonic() - self._start_time) * 1000),
        received_at=datetime.datetime.now(datetime.UTC).isoformat(),
    )
```

handler 里再次用 `PingCommand.model_validate(params)` 验证业务参数。这样**传输层只关心 JSON-RPC 外壳和 method 分发**，**业务 handler 负责自己的 payload**。职责边界很清楚：server 不需要知道每个 method 的字段，handler 也不需要知道 socket 怎么读写。

## `sagent ping` 完整数据流

```mermaid
flowchart LR
    subgraph CLI["sagent (CLI 进程)"]
        A["构造 JSON-RPC 请求\nmethod: core.ping / id: cli-1"]
        B["TCP 写入\nwriter.write(line + \"\\n\")"]
        I["解析 + 验证响应\njson.loads → model_validate"]
        J["打印 pong 结果\npong server=0.0.1 uptime=150ms"]
    end

    subgraph DAEMON["sagent-core (daemon 进程)"]
        C["json.loads + model_validate\nJsonRpcRequest 验证外壳"]
        D["dispatch → _ping_handler\nhandlers.get(core.ping)"]
        E["构造 PongResult\nserver_version / uptime_ms / received_at"]
        F["TCP 写回\nJsonRpcSuccess → writer.write"]
    end

    A --> B
    B -->|JSON-RPC 请求 NDJSON 行| C
    C --> D
    D --> E
    E --> F
    F -->|JSON-RPC 响应 NDJSON 行| I
    I --> J
```

一次 `sagent ping` 的完整旅程：

1. **CLI 构造请求** —— 组装 `{"jsonrpc":"2.0","id":"cli-1","method":"core.ping","params":{"client":"cli/0.0.1"}}`
2. **CLI TCP 写入** —— `json.dumps(req) + "\n"`，通过 `asyncio.open_connection` 发往 `127.0.0.1:7437`
3. **daemon 验证外壳** —— `json.loads()` 后 `JsonRpcRequest.model_validate()`，确认是合法的 JSON-RPC 请求
4. **daemon 路由分发** —— `handlers.get("core.ping")` 找到 `_ping_handler`
5. **daemon 业务处理** —— handler 内部再用 `PingCommand.model_validate(params)` 校验业务参数，构造 `PongResult`
6. **daemon TCP 写回** —— 把 `JsonRpcSuccess(id=req.id, result=pong.model_dump())` 序列化加 `\n` 写回
7. **CLI 解析响应** —— `json.loads()` → `JsonRpcSuccess.model_validate()` → `PongResult.model_validate()`
8. **CLI 打印结果** —— 格式化输出 `pong server=0.0.1 uptime=150ms latency=2ms`

## 协议文档从模型生成

到这里 `ping` 已经跑通了，但还有一个容易被忽视的问题：**协议文档怎么保持同步？**

如果手写 `WIRE_PROTOCOL.md`，后面每加一个 Command/Event 都要记得改文档。忘一次，文档就开始漂移。s0 的做法是反过来：**把 pydantic 模型当成协议源头，用脚本生成文档**。

```bash
uv run python scripts/gen_protocol_doc.py
uv run python scripts/gen_protocol_doc.py --check
```

`scripts/gen_protocol_doc.py` 遍历 `bus/commands.py` 和 `bus/events.py`，输出字段表、JSON Schema 和示例 payload 到 `WIRE_PROTOCOL.md`。

> 💡 这里的核心决策是"**代码是协议事实来源**"。文档当然要提交进仓库，方便阅读和 review；但文档内容不靠手工维护，而是从模型重新生成。

## 与 WIRE_PROTOCOL.md 的关系

[`WIRE_PROTOCOL.md`](../../WIRE_PROTOCOL.md) 是**自动生成**的协议文档，由 `scripts/gen_protocol_doc.py` 扫描 `core/bus/` 下的 Pydantic 模型生成。它包含了每个模型的 JSON Schema 和示例，是协议模型的**参考手册**。

而本文档（`protocol.md`）是**设计说明**，解释为什么选 NDJSON、JSON-RPC 怎么工作、以及代码层面的实现细节。两者互补。
