# LLM 拿到任务工具之后

这是整个 s3 最核心的一步，但没有新代码——完全靠 s1 建好的 `AgentLoop + AnthropicProvider` 机制，加上新的工具 schema。

`AgentLoop.run()` 的循环体没有变：

```
while not context.is_done():
    → plan:    provider.chat(messages, tool_schemas, ...)
    → observe: 把 LLM 响应追加进 context.messages
    → act:     对每个 tool_call 执行 invoke_tool()
    → 终止检查
```

变的是 `tool_schemas` 的内容——现在包含了 `task_create`、`task_update` 等 4 个任务工具的 schema。LLM 读到这些 schema 后，会根据 system prompt 的指示和它自己对"什么时候应该拆解任务"的判断，决定要不要在第一步就调用 `task_create`。

一次典型的多任务 run，`context.messages` 的演变是这样的：

```
step 1:
  → LLM: [task_create("分析目录结构"), task_create("读取核心模块", blocked_by=[1]), ...]
  → context.messages 追加 assistant 消息（tool_use blocks）
  → invoke_tool 依次执行，任务文件写入 .tasks/
  → context.messages 追加 user 消息（tool_result blocks）

step 2:
  → LLM: [task_update(1, "in_progress"), list_dir(".")]
  → ...

step 3:
  → LLM: [read_file("src/core/loop.py"), ...]
  → task_update(1, "completed") ← 触发 _clear_dependency，任务 2 的 blocked_by 被清空

step N:
  → LLM: [write_file("/tmp/report.md", content="...")]
  → task_update(N, "completed")
  → end_turn
```

---

# 任务工具与普通工具在事件流上的统一

这里有一个设计决策：**任务工具调用和普通工具调用在事件流上完全一样**。LLM 调用 `task_create` 产生的是 `tool.call_started` + `tool.call_finished` 事件，跟调用 `bash` 或 `read_file` 完全相同的格式。TUI 不需要知道"这是任务操作"——它只是看到一个工具调用，显示一个工具调用块。

任务系统是 agent 的认知行为，不是系统的控制操作，把它暴露成独立的事件类型反而会让 TUI 变得复杂。

