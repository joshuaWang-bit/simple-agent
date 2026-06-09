# Compactor：把历史压成交接摘要

`AgentRunner` 为每个 run 创建 `Compactor`：

```python
session_dir = store.session_dir(session.id) if session is not None else run_path
session_id_str = session.id if session is not None else ""
compactor = Compactor(bus, session_dir, session_id_str)
```

自动 compact 调的是：

```python
await self._compactor.compact(context, self._provider)
```

## 压缩后替换内存 messages

`compact()` 成功后会替换当前 run 的内存 messages：

```python
context.messages = [
    {"role": "user", "content": result.summary_text},
    {"role": "assistant", "content": "Understood, I'll continue from this summary."},
]
self._write_summary(result.summary_text)
await self._bus.publish(ContextCompactedEvent(...))
```

注意这个语义：**自动 compact 只改当前 run 的 `context.messages`，不覆盖 `thread.jsonl`。**

为什么还写 `summary_<ts>.md`？因为 compact 是有损的。如果后续 agent 行为变差，用户至少能打开 summary 文件，看当时压缩成了什么。

## 摘要 prompt 结构

摘要 prompt 不是"总结一下"。它要求六段结构：

```text
## 1. Original Goal
## 2. Completed Steps
## 3. Key Constraints & Discoveries
## 4. Current File State
## 5. Remaining TODOs
## 6. Critical Data
```

这六段对应 agent 接续任务时最容易丢的东西：原目标、已完成步骤、约束、文件状态、剩余任务、必须原样保留的 ID/错误/配置。

## 不调用工具

compact 调 LLM 时不提供工具：

```python
response = await provider.chat(
    messages=compress_request,
    tool_schemas=[],
    bus=silent_bus,
    run_id="compact",
    step=0,
    system="You are a helpful assistant that summarizes conversations.",
)
```

摘要任务不应该再调工具。它只能读已有历史，写一份 handoff summary。

失败时也很保守：provider 抛异常、摘要为空，都返回 `None`，调用方保留原 messages 继续跑。compact 是续航优化，不应该让用户任务失败。
