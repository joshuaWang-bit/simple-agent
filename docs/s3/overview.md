# S3-trace

## Trace：让 daemon 的数据流从黑盒变成时间线

| 项目 | 内容 |
|------|------|
| **阶段** | trace |
| **分支** | `stage/s3` |
| **本阶段新增** | TraceRecord、TraceWriter、TracingProvider、IPC / EventBus / LLM 三层埋点、`kama trace` CLI |
| **依赖上一阶段** | s2 的 SocketServer、IpcEventBroadcaster、EventBus、AnthropicProvider |

## 本阶段要做什么

s2 结束时，我们已经能把任务跑起来，而且两个终端能同时看到同一份事件流。`runs/<run_id>/events.jsonl` 里有完整的步骤序列：哪步开始了，哪个工具被调用，LLM 用了多少 token。

但这只是**一个视角**——EventBus 内部的视角。

假设你运行了一次任务，得到了错误的结果。你想搞清楚到底哪里出问题：

- LLM 真的收到了工具调用的结果吗？`messages` 参数里有没有正确的 `tool_result`？
- LLM 的 `stop_reason` 是 `tool_use` 还是 `end_turn`？它是主动结束还是被截断了？
- 客户端发来的 `agent.run` 命令，参数有没有被正确解析？还是在 IPC 层就已经出了问题？

`events.jsonl` 回答不了这三个问题。它只记录了 EventBus 发布的高层事件，不包含 IPC 层的 JSON-RPC 原始帧，也不包含发给 Anthropic API 的完整 `messages` 数组和收到的原始响应。

这个阶段要在系统里埋四个观察点，把三个层面的数据流统一汇入一个文件，按时间顺序排成一条时间线：客户端发来什么命令，守护进程回了什么，EventBus 发布了什么事件，LLM API 收到和返回了什么——全部可见，全部有时间戳，全部可以用命令行过滤查看。
