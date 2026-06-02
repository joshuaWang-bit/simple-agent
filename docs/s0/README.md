# S0 — 项目基础架构

> 第 0 阶段：从零开始搭建 SimpleAgent 的骨架。

## 阶段信息

| 项目 | 内容 |
|------|------|
| 阶段 | s0 |
| 分支 | `stage/s0` |
| 本阶段新增 | 项目脚手架、配置系统、协议模型、TCP NDJSON 传输层、CLI 与 daemon 的 ping/pong 握手 |
| 依赖上一阶段 | 无 |

## 本阶段目标

我们要从一个空仓库开始搭 **SimpleAgent**。最终它会是一个本地运行的 AI Agent 系统：

- 后台有一个常驻的 `sagent-core` 守护进程
- 前台有 `sagent` CLI 和后续的 TUI
- 所有真正的任务执行都发生在 Core 里

但 **s0 不急着接 LLM，也不急着写工具**。这个阶段只做一件看起来很小、但决定后面所有结构的事情：**让 CLI 和 daemon 通过一条真实的进程间通信链路完成一次握手。**

## 快速体验

开两个终端：

```bash
# 终端 A
uv run sagent-core

# 终端 B
uv run sagent ping
```

你应该能看到类似这样的输出：

```
pong server=0.0.1 uptime=150ms latency=2ms
```

## 这条 `ping` 路径的主线

用户敲下 `sagent ping` 之后，数据流如下：

1. **CLI 读取配置** —— 从 `~/.sagent/config.toml` 和环境变量加载
2. **连接 daemon** —— TCP 连接到 `127.0.0.1:7437`
3. **发出请求** —— 发送一行 JSON-RPC 请求：
   ```json
   {"jsonrpc":"2.0","id":"cli-1","method":"core.ping","params":{"client":"cli/0.0.1"}}
   ```
4. **daemon 读取** —— `SocketServer` 用 `readline()` 读到这一行
5. **验证协议** —— 验证成 `JsonRpcRequest` 协议模型
6. **分发处理** —— 根据 `method` 路由到 `core.ping` handler
7. **构造响应** —— handler 返回 `PongResult`，包含版本、运行时间、收到时间
8. **写回结果** —— daemon 把 JSON-RPC Success 响应写回客户端
9. **CLI 展示** —— 解析响应，格式化输出 `pong server=... uptime=...ms latency=...ms`

我们会顺着这条路径一站一站搭系统。后续文档将分别介绍：

- [`architecture.md`](architecture.md) —— 整体架构设计
- [`structure.md`](structure.md) —— 项目目录与模块划分
- [`config.md`](config.md) —— 配置系统与 CLI 入口
- [`protocol.md`](protocol.md) —— 协议模型与传输层细节

## 小结与展望

s0 没有让 Agent 做任何任务，但它把后续所有功能要站在上面的地基先打好了。

我们有了稳定的项目脚手架，CLI 和 daemon 可以通过 `pyproject.toml` 声明的入口启动；有了可覆盖的配置系统，开发、测试、部署都能用同一套 `AgentConfig`；有了 JSON-RPC 2.0 over TCP + NDJSON 的传输层，进程间消息有清晰的定界、路由和错误响应；有了 pydantic 协议模型，坏消息会在边界处失败；还有了从代码生成的 `WIRE_PROTOCOL.md`，协议文档不会靠人工记忆维持同步。

当前系统的局限也很明显：daemon 只会回答 `core.ping`，不会调用 LLM，不会执行工具，也没有真正的事件流给客户端订阅。它像一个已经接好电源和网线的空房间，能证明线路通了，但里面还没有机器开始工作。

s1 会在这条骨架上接入第一个真实能力：`sagent run --goal "..."`。到那时，配置系统会开始提供 LLM 模型和密钥，协议层会增加新的命令，Core 里会出现 Agent 循环、工具注册表和事件日志。
