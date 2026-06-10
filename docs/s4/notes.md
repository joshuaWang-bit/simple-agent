# notes.md：agent 自己给未来留笔记

只有 thread 够不够？s4 阶段短对话里，确实看起来够。

第一轮 thread 已经记录了 `pyproject.toml` 里的 Python 版本，第二轮完整回放时 LLM 能看到。那为什么还要 `notes.md`？

因为 thread 是"历史流水"，notes 是"事实层"。s6 会引入 compact：当 thread 过长时，旧消息会被压缩成摘要。摘要可能漏掉某个细节，但 notes 不参与 compact，会原样注入 system prompt。

s4 先把这条契约建立起来：agent 在知道某件事以后，可以主动调用 `note_save` 记录它。

```python
# src/simple_agent/core/tools/note_save.py（节选）

class NoteSaveTool(BaseTool):
    name = "note_save"
    description = (
        "Save a fact or decision to the session's notes. "
        "These notes will be visible to you in future turns of this session."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
        },
        "required": ["content"],
    }

    def __init__(self, store, session_id, run_id):
        self._store = store
        self._sid = session_id
        self._run_id = run_id

    async def invoke(self, params):
        content = str(params["content"]).strip()
        if not content:
            return ToolResult(content="empty content", is_error=True)
        self._store.append_note(self._sid, content, self._run_id)
        return ToolResult(content="saved")
```

这个工具只在 session run 里注册：

```python
if session is not None and store is not None and run_id is not None:
    registry.register(NoteSaveTool(store, session.id, run_id))
```

没有 session 的普通 run 不应该看到 `note_save`。因为 `note_save` 的语义就是"写当前 session 的 notes"，没有 `session_id` 就没有写入目标。

为什么不在每次 run 结束后自动总结，把摘要写入 notes？

自动总结有三个问题：

- 多一次 LLM 调用，增加延迟和成本。
- 事后总结是在猜哪些内容未来重要。
- agent 自己知道哪些值得记，比外部启发式规则更精确。

## notes 怎么进入 LLM：注入 system prompt

`ExecutionContext` 收到 `session_notes` 后，不把它塞进 messages，而是拼进 system prompt：

```python
# src/simple_agent/core/context.py（节选）

def system_prompt(self, base: str) -> str:
    if not self.session_notes.strip():
        return base
    return (
        base
        + "\n\n## Session Notes\n"
        + self.session_notes.strip()
        + "\n\nRemember important durable facts by calling note_save."
    )
```

为什么放 system，而不是伪造一条 user 消息？

notes 不是某一轮用户说的话，它是会话层的持久上下文。放进 system prompt，能让模型把它当作当前会话背景，而不是误以为用户刚刚又说了一遍。

`AgentLoop` 调 LLM 时，把这个动态 system 传给 provider：

```python
response = await self._provider.chat(
    messages=context.messages,
    tool_schemas=self._registry.tool_schemas(),
    bus=self._bus,
    run_id=context.run_id,
    step=context.step,
    system=context.system_prompt(BASE_SYSTEM_PROMPT),
)
```

这里有一个缓存上的取舍。notes 一变，system prompt 也变，下一次 prompt cache 会重建一次。这个代价可以接受，因为 notes 不应该每一步都变；而当 notes 真的变了，让模型立即看到新事实比缓存命中更重要。

> ⚠️ notes 是本地 agent 写入的受信任上下文。s4 不处理 notes 里的 prompt injection。后续权限和上下文治理阶段会继续收紧边界。
