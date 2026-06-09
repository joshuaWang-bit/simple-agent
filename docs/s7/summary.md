# 小结与展望

s7 把系统从"一个 agent 使用内建工具"推进到"可组织、可派生、可扩展"：

- **Skills** 把常用工作流固化成斜杠命令，并能限制父 agent 的工具集。
- **Subagents** 把复杂任务拆给隔离上下文里的子 agent，每个子 agent 可以有自己的角色和工具边界。
- **事件桥** 让子 agent 的输出仍然进入同一条 TUI 事件流。
- **后台 subagent** 和 `agent_result` 让并行任务成为可能。
- **MCP** 把外部工具服务器接进同一套 ToolRegistry/invoke_tool/EventBus 链路。
