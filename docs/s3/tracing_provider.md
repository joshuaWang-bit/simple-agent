# 埋点 ④：LLM 层——TracingProvider

LLM 层的 trace 用了一个不同的思路：不是在 `AnthropicProvider` 里埋点，而是在它外面套一层。

`TracingProvider` 实现了和 `AnthropicProvider` 完全相同的 `LLMProvider` 接口，内部持有一个 `inner` provider 的引用：

```python
# core/trace/provider.py（节选）

class TracingProvider:
    def __init__(self, inner: LLMProvider, trace: TraceWriter, *, include_payload: bool) -> None:
        self._inner = inner
        self._trace = trace
        self._include_payload = include_payload

    async def chat(self, messages, tool_schemas, bus, run_id, *, step=0) -> LlmResponse:
        # 调用前：记录 CORE→LLM
        if self._include_payload:
            call_data = {"messages": messages, "tool_schemas": tool_schemas}
        else:
            call_data = {"message_count": len(messages), "tool_count": len(tool_schemas)}

        self._trace.emit(TraceRecord(
            direction="CORE→LLM", layer="llm", kind="api_call",
            run_id=run_id, step=step, data=call_data,
        ))

        t0 = time.monotonic()
        result = await self._inner.chat(messages, tool_schemas, bus, run_id, step=step)
        latency_ms = int((time.monotonic() - t0) * 1000)

        # 调用后：记录 LLM→CORE
        ...
        self._trace.emit(TraceRecord(
            direction="LLM→CORE", layer="llm", kind="api_response",
            run_id=run_id, step=step, data=resp_data,
        ))
        return result
```

> **为什么用 wrapper 而不是直接在 AnthropicProvider 里加？** `AnthropicProvider` 是一个具体实现，它应该只关心"怎么调 Anthropic API"。如果 trace 逻辑写进去，以后想换一个 provider，或者想关掉 trace，就得改两个地方。Wrapper 模式让两者完全解耦：trace 禁用时，`AgentRunner` 直接用 `AnthropicProvider`；启用时，在外面套一个 `TracingProvider`，`AnthropicProvider` 本身一行代码都不改。

`include_payload` 控制是否记录完整的 `messages` 数组和响应体。默认开启——调试时能看到 LLM 实际收到的完整 prompt 非常有价值，能直接看出是提示词有问题还是工具结果传递有问题。生产场景（message 可能包含敏感信息，或者 trace 文件体积需要控制）可以关掉，只记录摘要。

`AgentRunner` 在收到非 None 的 `trace` 时，用 `TracingProvider` 包裹真实 provider：

```python
# core/runner.py（节选）

if self._trace is not None:
    provider = TracingProvider(
        provider,
        self._trace,
        include_payload=self._config.trace.include_llm_payload,
    )
```

同时，为了让 `TracingProvider` 能把步骤编号记录进 `LLM→CORE` 记录，`AgentLoop` 在调 `provider.chat()` 时需要把当前步骤传进去。原来的调用：

```python
response = await self._provider.chat(messages=context.messages, ...)
```

改成：

```python
response = await self._provider.chat(messages=context.messages, ..., step=context.step)
```

`LLMProvider` 协议和 `AnthropicProvider` 的签名同步加上 `*, step: int = 0` 关键字参数。`AnthropicProvider` 不使用这个参数（它不需要知道步骤编号），只是接受它以满足协议约定。

## 配置

`config.toml` 里的 `[trace]` 小节：

```toml
[trace]
enabled = true
file = "~/.kama/traces/daemon.jsonl"
include_llm_payload = true
```

对应的环境变量：`KAMA_TRACE_ENABLED`、`KAMA_TRACE_FILE`、`KAMA_TRACE_INCLUDE_LLM_PAYLOAD`。
