# TraceRecord：时间线里的每一行

每条 trace 记录都是一个 `TraceRecord`：

```python
# core/trace/record.py

class TraceRecord(BaseModel):
    ts: str
    direction: Literal[
        "CLIENT→CORE", "CORE→CLIENT", "CORE", "CORE→LLM", "LLM→CORE"
    ]
    layer: Literal["ipc", "event", "llm"]
    kind: str
    run_id: str | None = None
    step: int | None = None
    client_id: str | None = None
    data: dict[str, Any]
```

`direction` 和 `layer` 的组合决定了这条记录的含义：`layer` 告诉你是哪个子系统，`direction` 告诉你数据在往哪里流。`kind` 是更细的分类：同样是 `CORE→CLIENT` 方向，`response` 是命令的 JSON-RPC 回复，`push` 是 broadcaster 主动推出去的事件推送，两者需要区分。

`data` 是开放的 `dict`——不同埋点塞进去的内容不同，IPC 层放原始帧结构，LLM 层放消息数量和 token 统计，不强制统一 schema，保持灵活。
