# 设计：系统级统一时间线

## 一个文件，五个方向

整个系统的数据流可以用五个方向描述完：

| 方向 | 含义 | 所在层 |
|------|------|--------|
| `CLIENT→CORE` | 客户端发来的 JSON-RPC 命令 | ipc |
| `CORE→CLIENT` | 守护进程回复的响应或主动推送的事件 | ipc |
| `CORE` | EventBus 内部发布的事件 | event |
| `CORE→LLM` | 发出 Anthropic API 请求 | llm |
| `LLM→CORE` | 收到 Anthropic API 响应 | llm |

这五个方向完整覆盖了 daemon 进程边界内外的所有 I/O。每条记录都有时间戳，按时间顺序追加到 `~/.kama/traces/daemon.jsonl`，整个文件就是系统行为的完整时间线。

```
四个埋点覆盖五个方向的数据流

Client                    kama-core                     Anthropic API
  │                           │                               │
  │ ① CLIENT→CORE            │                               │
  │ ② CORE→CLIENT            │                               │
  ▼                           ▼                               │
kama / kama-tui  ←──────→  SocketServer  ←──①②──→          │
                               │                              │
                               ▼                              │
                            EventBus  ←──③──→                │
                               │                              │
                               ▼                              │
                         TracingProvider ←──④──→  Anthropic API
                                    CORE→LLM / LLM→CORE
```

四个埋点的 `emit()` 均写入 `~/.kama/traces/daemon.jsonl`，按全局时间顺序排列。

## 为什么是一个文件，而不是每个 run 一个文件

看起来把 trace 记录拆到 `runs/<run_id>/trace.jsonl` 更整洁——每次 run 自己管自己的 trace。

但有一个问题：`CLIENT→CORE` 命令在被解析成功之前，`run_id` 还不存在。客户端发来 `agent.run`，守护进程解析出命令、生成 `run_id`、启动 AgentRunner——这三件事有先后顺序，第一条 trace 记录在第三件事之前就必须写出去。

更大的问题是 IPC 命令本身：`core.ping`、`event.subscribe` 这类命令根本就没有关联的 `run_id`，它们是全局性的守护进程行为，不属于任何一次 run。

所以存储的选择很明确：单一的 `daemon.jsonl`，daemon 整个生命周期的全局时间线，`run_id` 是可选字段——有就记，没有就留空。

> 这个决策和 `events.jsonl` 形成了互补：`events.jsonl` 是 per-run 的深度档案，适合分析"这次 run 里 agent 做了什么"；`daemon.jsonl` 是跨层的系统时间线，适合调试"这条命令是怎么一路流转的"。两个文件各有用途，不冲突。

## 非阻塞写入：队列 + drain task

`emit()` 是在 EventBus 回调里被调用的，这个回调在 daemon 的主 asyncio 事件循环里运行。如果 `emit()` 直接调用文件 I/O，哪怕是极短的阻塞（几毫秒），也会卡住事件循环，让所有在等待的协程一起暂停。

解决方案：`emit()` 只把记录放进一个内存队列（`asyncio.Queue.put_nowait`），立即返回；一个独立的 drain task 持续从队列里取出记录，追加写入文件。主事件循环从不等文件 I/O。

```
emit() → asyncio.Queue → _drain() → 追加写 daemon.jsonl
         （非阻塞，立即返回）         （独立 task，异步执行）
```

> 这个设计有一个后果：如果 daemon 突然崩溃（SIGKILL），队列里还没来得及写出的记录会丢失。SIGTERM 不会丢，因为 `CoreApp.run()` 在关闭时会调用 `trace.stop()`，它等待队列清空再退出。课程项目里这个权衡是合理的——调试时不会 SIGKILL 进程。
