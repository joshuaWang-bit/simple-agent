# 小结与展望

s6 给 s4 完整回放加了治理层：

- 三层 context 把稳定背景放进 system prompt。
- `tool_result` 截断让大输出不再每轮完整占用上下文。
- `context_pct` 让上下文水位进入事件流。
- 自动 compact 解决当前 run 的续航。
- 手动 `/compact` 给用户一个明确的持久化压缩入口。

这一步之后，agent 可以在更长的会话里继续工作。但它仍然是一个 agent 在一条执行线上做事。下一阶段 s7 会把边界继续往外推：用 skills 固化工作流，用 subagents 拆分角色，用 MCP 接入外部工具服务器。
