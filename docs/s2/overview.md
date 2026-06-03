# S2-把事件流外化为 IPC

## 第 2 阶段：把事件流外化为 IPC

| 项目 | 内容 |
|------|------|
| **阶段** | s2 |
| **分支** | `stage/s2` |
| **本阶段新增** | daemon 执行 agent.run、IPC 事件推送、事件订阅与回放、SocketClient、TUI 雏形、daemon 生命周期管理 |
| **依赖上一阶段** | s1 的 AgentRunner、AgentLoop、EventBus、EventWriter |

## 根本目标

s2 要修正的根本问题不是"增加一个 TUI"，也不只是"把 `AgentRunner.run()` 换个地方调用"。真正的目标是：**把 s1 的进程内事件总线外化为 IPC，让 Core daemon 成为唯一的 agent 执行体，CLI 和 TUI 都通过同一份协议消费同一份实时事件流**。

这会解决三个具体限制：

- 多客户端可以同时消费同一份 run 事件，CLI 和 TUI 不再各跑各的。
- S0 建好的 daemon、SocketServer 和 JSON-RPC 协议开始承载真正的 agent 命令，而不是只响应 `core.ping`。
- 客户端断开后可以通过 `events.jsonl` 回放历史，再接续实时事件流。

所以 s2 的主线是 `kama run --goal "..."` 的双进程版：CLI 发送 `event.subscribe` 和 `agent.run`，daemon 在后台运行 AgentRunner，EventBus 把事件同时交给 EventWriter 和 IpcEventBroadcaster，所有客户端从同一条 IPC 事件流里观察进度。

## s1 → s2: AgentRunner 的位置变化

### s1: AgentRunner 在 CLI 进程里

```
kama run
    ↓
AgentRunner
    ↓
EventBus → StdoutPrinter
         → EventWriter
```

### s2: AgentRunner 在 daemon 里

```
kama CLI ──命令──→ SocketServer ──→ AgentRunner ──→ EventBus ──→ EventWriter
    ↑                                              │
    └──────────── 事件推送 ←─────────────────────────┘
                                                      ↓
                                               IpcEventBroadcaster
```

kama-tui 也通过 SocketClient 连接进来，与 CLI 共用同一份事件流。
