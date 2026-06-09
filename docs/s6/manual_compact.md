# 手动 /compact：持久化改写 thread

自动 compact 是 run 内临时续航。用户明确输入 `/compact` 时，语义不同：我要把这个 session 的历史压掉。

IPC 命令是 `session.compact`：

```python
class SessionCompactCommand(BaseModel):
    type: Literal["session.compact"] = "session.compact"
    session_id: str
    focus: str = ""
```

`SessionManager.compact()` 会拿 session 锁，读 messages，调用同一个 `compact_messages()`，然后写回：

```python
result = await compactor.compact_messages(messages, self._provider, focus=focus)
if result is None:
    raise HandlerError(-32021, "compaction failed or not beneficial")
self._store.write_compacted(sid, [
    {"role": "user", "content": result.summary_text},
    {"role": "assistant", "content": "Understood, I'll continue from this summary."},
])
```

`write_compacted()` 会覆盖 `thread.jsonl`，并把原文件备份成 `.bak`。

## 手动和自动的边界

| 触发方式 | 改内存 messages | 改 thread.jsonl | 用途 |
|----------|----------------|-----------------|------|
| 自动 compact | 是 | 否 | 当前 run 快满了，先续航 |
| `/compact` | 是（下次读取生效） | 是 | 用户明确压缩会话历史 |

> ⚠️ 手动 compact 是持久化操作。它会保留备份，但当前 session 后续读取的就是摘要版 thread。

---

# TUI：把上下文水位显示出来

TUI 收到 `llm.usage` 后会保存 `context_pct`，并渲染一条 tokens 行：

```python
elif t == "llm.usage":
    pct = float(event.get("context_pct") or 0.0)
    self._last_context_pct = pct
    ctx_bar = self._render_ctx_bar(pct)
    self._append(Static(
        f"tokens in={event.get('input_tokens')} "
        f"out={event.get('output_tokens')} "
        f"cache={event.get('cache_read_input_tokens')} "
        f"{ctx_bar}",
        classes="usage",
    ))
```

收到 `context.compacted` 后，TUI 追加一行提示，并把水位重置：

```python
elif t == "context.compacted":
    self._last_context_pct = 0.0
    self._append(Static(
        f"Context compacted original={orig} tokens → summary={summary} tokens",
        classes="log-line",
    ))
```

这里的 UI 不参与决策。它只是把 provider 和 compactor 发布的事实事件展示出来。真正的触发逻辑仍然在 AgentLoop 和 SessionManager。
