# context_pct：先让水位可见

要决定什么时候 compact，必须先知道当前用了多少上下文。

Anthropic final message 会返回 usage。s6 在 provider 里把 input token 除以模型上下文窗口，得到 `context_pct`：

```python
# core/llm/provider.py（节选）

context_pct = usage.input_tokens / _context_window(self._model)

await bus.publish(
    LlmUsageEvent(
        run_id=run_id,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_create,
        context_pct=context_pct,
        ts=_now(),
    )
)
```

`LlmUsageEvent` 原本只是给用户看 token 数。现在它也变成上下文治理信号：

- TUI 用它画上下文水位。
- AgentLoop 用它判断是否触发自动 compact。

这延续了 s2 的事件流设计：provider 只发布事实，谁需要谁订阅。

## LlmUsageEvent 的两个消费者

```
AnthropicProvider
  final_message.usage
         │
         ▼
   LlmUsageEvent
(input / output / cache / context_pct)
    │              │
    │              └──── 治理判断 ────→ AgentLoop
    │                                     (context_pct ≥ threshold?)
    │                                              │
    │                                              ▼
    │                                         Compactor
    │
    └──── 展示 ────→ TUI
                       (tokens 行 + context bar)
```

同一个 usage 事实，同时驱动 UI 和治理逻辑。
