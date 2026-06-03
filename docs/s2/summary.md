# 小结与展望

s2 的核心是把 s1 的进程内事件流变成 daemon 对外提供的 IPC 事件流。`AgentRunner` 开始在 Core daemon 中运行，CLI 和 TUI 都通过 `SocketClient` 连接 daemon，先订阅事件，再发送 `agent.run`，随后从同一条 NDJSON 连接中接收命令响应和事件推送。

这个阶段新增了几条关键边界：

- **daemon 是唯一执行体**：`kama run` 不再直接创建 `AgentRunner`，而是发送 `agent.run` 命令。
- **EventBus 变成 daemon 级事件源**：`EventWriter` 继续写 `events.jsonl`，`IpcEventBroadcaster` 同时把事件推给 TCP 客户端。
- **客户端共享同一套 IPC 代码**：CLI 和 TUI 都复用 `SocketClient`，请求-响应用 `Future` 配对，事件推送用回调分发。
- **断线后可以回放历史**：`event.subscribe` 支持 `replay_from_run`，客户端能先读取 `events.jsonl`，再接续实时流。

目前的限制也很明确：s2 只验证双进程架构和事件流外化，不处理多任务调度。daemon 同一时刻只支持一个活跃 run，新请求会被拒绝；s3 会在这个 IPC 基础上引入任务状态机和更完整的任务视图。
