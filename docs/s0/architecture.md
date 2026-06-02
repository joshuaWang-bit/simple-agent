# S0 架构设计

## 双进程拓扑

SimpleAgent 从 s0 开始就是**双进程系统**，不是先写成单进程脚本、后面再拆。

```
sagent-core (daemon)
    │
    │  TCP loopback  127.0.0.1:7437
    │  NDJSON 帧
    │
    ├── sagent (CLI, 一次性命令)     ← S0 已实现
    └── sagent-tui (TUI, S2+ 实现)   ← 预留
```

```
┌─────────────────┐                      ┌─────────────────┐
│  sagent-core    │ ◄── TCP / NDJSON ──► │   sagent CLI    │
│ daemon/asyncio  │     127.0.0.1:7437   │  (前台进程)      │
│  ├─ bus (协议)   │                      └─────────────────┘
│  ├─ transport   │
│  └─ config      │
└─────────────────┘
         ▲
         │  TCP 127.0.0.1:7437 / NDJSON   (S2+ 实现)
         │
    ┌─────────────────┐
    │  sagent-tui     │
    │  TUI (S2+ 实现)  │
    └─────────────────┘
```

s0 阶段只有两个角色：

1. **CLI (`sagent`)** —— 一次性前台命令，执行完即退出
2. **Core (`sagent-core`)** —— 常驻后台的 asyncio TCP 服务器

两者通过 **TCP + NDJSON（每行一个 JSON 对象）** 进行通信，协议载体为 **JSON-RPC 2.0**。

### Core 是唯一执行体

**所有任务、工具调用、LLM 调用都只在 Core 进程内发生；CLI 和 TUI 只是客户端，不持有核心状态。**

这个约束看起来会让 s0 多写一些通信代码，但它避免了后面最痛的一类返工：把已经写好的内部函数调用全部改成序列化、网络传输和异步响应。

> 💡 s0 选择"第零天就拆进程"，不是为了复杂而复杂。进程边界一旦存在，数据就必须能被序列化，调用就必须能失败，响应就必须能和请求对应。越早把这些约束放进代码里，后续阶段写 Agent 循环时越不容易走偏。

## 为什么选择 NDJSON over TCP？

- **简单**：`readline()` 即可解决粘包/拆包，无需处理长度前缀或帧头
- **人可调试**：`nc 127.0.0.1 7437` 敲一行 JSON 就能交互
- **可扩展**：后续如果需要流式输出（如 SSE 风格的逐 token 推送），每行一个事件天然适配
- **轻量**：s0 不需要 WebSocket、gRPC 或 Unix Domain Socket 的额外复杂度

## 配置分层

配置按优先级从低到高：

1. **代码默认值** —— `AgentConfig` 中的字段默认值
2. **TOML 配置文件** —— `~/.sagent/config.toml`
3. **环境变量** —— `SAGENT_HOST`, `SAGENT_PORT`, `SAGENT_LOG_LEVEL`
4. **`.env` 文件** —— 开发时本地覆盖（通过 `python-dotenv`）

```python
class AgentConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 7437
    log_level: str = "INFO"
```

## 请求处理流程

```
TCP 连接建立
    │
    ▼
readline() ──► json.loads() ──► JsonRpcRequest.validate()
                                    │
                                    ▼
                            查找 handlers[req.method]
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
              handler 存在                    handler 不存在
                    │                               │
                    ▼                               ▼
            调用 handler(params)            返回 METHOD_NOT_FOUND
                    │
                    ▼
            返回 Pydantic 模型
                    │
                    ▼
            JsonRpcSuccess(result=...)
                    │
                    ▼
            model_dump_json() + "\n"
                    │
                    ▼
              writer.write()
```

## 错误处理

服务端按 JSON-RPC 2.0 规范返回错误码：

| 错误码 | 含义 | 触发场景 |
|--------|------|----------|
| `-32700` | Parse error | JSON 解析失败 |
| `-32600` | Invalid Request | 请求结构不符合 JsonRpcRequest |
| `-32601` | Method not found | 没有注册对应的 handler |
| `-32602` | Invalid params | handler 参数校验失败（Pydantic ValidationError） |
| `-32603` | Internal error | handler 抛出的其他异常 |
