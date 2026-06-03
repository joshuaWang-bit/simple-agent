# 执行路径概览

先把 s2 里 `kama run --goal "..."` 的完整执行路径过一遍。后面的章节会按这条路径展开。

## 客户端侧（`kama` 进程）

1. 连接守护进程的 TCP 端口（默认 `127.0.0.1:7437`）
2. 发送 `event.subscribe` 命令：告诉守护进程想订阅哪些事件类型
3. 发送 `agent.run` 命令，附上 goal
4. 守护进程立刻回复一个 `run_id`（不等任务完成）
5. 继续监听同一条连接，接收守护进程主动推过来的事件
6. 每收到一个事件，`StdoutPrinter` 格式化打印
7. 收到 `run.finished`，关闭连接，退出

## 守护进程侧（`kama-core` 进程）

1. 收到 `event.subscribe`，把这条连接的 TCP 写端登记到 broadcaster
2. 收到 `agent.run`，生成 `run_id`，后台启动 `AgentRunner.run()`，立即回复 `run_id`
3. `AgentRunner` 在后台运行，向全局 `EventBus` 发布事件
4. `IpcEventBroadcaster` 订阅了这个 bus，把每个事件推给所有登记的客户端

s1 的组件（AgentRunner、AgentLoop、EventBus、EventWriter）都还在。变化在边界上：`EventBus` 从单个 CLI 进程里的局部对象，变成 daemon 生命周期内的全局事件源；`IpcEventBroadcaster` 成为它的订阅者，把事件推给 TCP 客户端；CLI 和 TUI 都通过 `SocketClient` 连接进来。
