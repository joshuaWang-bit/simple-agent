# s1 小结

## 这一阶段我们学到了什么

- **EventBus 模式**：把"事情发生了"和"怎么响应"解耦，核心逻辑干净，测试方便
- **ExecutionContext**：agent 的记忆 = 消息历史，格式和 OpenAI 兼容 API 对齐，零转换成本
- **AgentLoop 三阶段**：plan（LLM 思考）→ observe（记录响应）→ act（执行工具），顺序由 OpenAI 兼容 API 格式要求决定
- **工具契约**：`invoke_tool` 永不抛异常，失败也是结果，让 LLM 自己决定怎么办
- **流式输出**：`stream=True` + `LlmTokenEvent` 实现终端打字机效果，支持硅基流动三档模型切换
- **事件持久化**：`events.jsonl` 每行一个 JSON，完整可追溯，flush 保证不丢数据

## s2 展望

s1 的 agent 能做事了，但只有一个 `read_file` 工具，且每次运行都要新建 HTTP 连接、重新加载模型上下文。s2 会解决：

- **工具扩展**：新增更多工具（shell、grep、write_file 等）
- **长时运行**：支持守护进程模式，agent 持续在线，接受多次任务
- **状态恢复**：运行中断后能从中断点恢复，而不是从头开始
- **多 provider 支持**：基于 OpenAI 兼容协议，可接入硅基流动、OpenAI、本地模型等
