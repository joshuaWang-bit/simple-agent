# tool_result 截断：只改内存，不改历史

上下文膨胀最快的来源通常不是用户聊天，而是工具输出。

比如：

```text
pytest -vv
```

失败时可能输出几万字符。如果这段完整内容每一轮都进入 prompt，context 很快被吃掉。

## 第一层保护

s6 的第一层保护是 `truncate_tool_results()`：

```python
TOOL_RESULT_LIMIT = 8_000
TOOL_RESULT_KEEP = 4_000

def truncate_tool_results(messages, limit=TOOL_RESULT_LIMIT, keep=TOOL_RESULT_KEEP):
    result = []
    for msg in messages:
        if msg.get("role") != "user":
            result.append(msg)
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            result.append(msg)
            continue
        new_blocks = []
        for block in content:
            if block.get("type") == "tool_result" and isinstance(block.get("content"), str):
                text = block["content"]
                if len(text) > limit:
                    omitted = len(text) - keep
                    block = dict(block)
                    block["content"] = (
                        text[:keep]
                        + f"\n[... {omitted} chars omitted. Full output in run events.]"
                    )
                new_blocks.append(block)
        result.append({**msg, "content": new_blocks})
    return result
```

它只处理 Anthropic 消息结构里的 `tool_result`。并且它返回新 list，不改原对象。

## 接入点

接入点在 `SessionStore.read_messages()`：

```python
messages = self._trim_orphan_tool_use(messages)
return truncate_tool_results(messages)
```

这句放在 `_trim_orphan_tool_use` 后面。先保证工具调用配对合法，再处理内容长度。

最重要的是：`thread.jsonl` 原文不变。截断只发生在"读出来准备发给 LLM"的内存版 messages 上。需要审计或排查时，完整工具输出仍然在 run 的 `events.jsonl` 和 thread 原文里。

> 💡 这不是 compact。它不调用 LLM，不生成摘要，不改写磁盘，只是把超长工具结果从每次 prompt 里拿掉一部分。
