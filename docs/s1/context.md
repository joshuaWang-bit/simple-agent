# ExecutionContext -- Agent 的记忆

`ExecutionContext` 是 agent 的工作记忆，在整个循环里被所有组件共享和修改：

```python
# core/context.py

@dataclass
class ExecutionContext:
    run_id: str
    goal: str
    max_steps: int
    messages: list[dict[str, Any]] = field(default_factory=list)
    step: int = 0
    status: str = "running"   # "running" | "success" | "failed"
    reason: str | None = None

    def __post_init__(self) -> None:
        # goal 在初始化时自动变成第一条对话消息
        if not self.messages:
            self.messages.append({"role": "user", "content": self.goal})
```

`messages` 是整个上下文最核心的部分。它的格式和 **OpenAI 兼容 API** 对齐，调用 LLM 时直接把 `context.messages` 传进去，不需要任何转换。

随着循环推进，`messages` 会不断追加新内容：

```python
    def add_assistant_message(
        self, content: str, tool_calls: list[dict] | None = None
    ) -> None:
        msg: dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self.messages.append(msg)

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        self.messages.append(
            {"role": "tool", "tool_call_id": tool_call_id, "content": content}
        )
```

OpenAI 格式的要求是：
- `assistant` 消息可以带 `tool_calls` 数组（每个元素有 `id`、`type`、`function`）
- `tool` 消息必须有 `tool_call_id` 和 `content`，紧接在对应的 `assistant` 消息之后

这样 LLM 才能在下一轮正确理解"我之前要求调用了什么工具，现在拿到了什么结果"。
