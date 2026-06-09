# 失败分类和重试

权限通过之后，工具本身也会失败。s5 把失败分成几类：

| error_class | 含义 | 是否重试 |
|-------------|------|----------|
| `schema_error` | LLM 参数格式错 | 否 |
| `permission_denied` | 用户拒绝 | 否 |
| `timeout` | 工具执行超时 | 否 |
| `runtime_error` | 运行时错误 | 是 |
| `rate_limited` | 上游限速 | 是 |

## 重试循环

重试循环在 `invoke_tool()` 里：

```python
_MAX_RETRIES = 2
_RETRY_BASE_S = 2.0
_RETRYABLE = {"runtime_error", "rate_limited"}

for attempt in range(1, _MAX_RETRIES + 2):
    try:
        result = await asyncio.wait_for(tool.invoke(dict(tool_call.input)), timeout=timeout)
        if result.is_error:
            error_class = result.error_type or "runtime_error"
            error_message = result.content
        else:
            await bus.publish(ToolCallFinishedEvent(...))
            return result
    except RateLimitedError as exc:
        error_class = "rate_limited"
        error_message = str(exc)
    except TimeoutError:
        return await _fail(..., "timeout", ...)
    except Exception as exc:
        error_class = "runtime_error"
        error_message = str(exc)

    if error_class in _RETRYABLE and attempt <= _MAX_RETRIES:
        await bus.publish(ToolCallFailedEvent(..., attempt=attempt))
        await asyncio.sleep(_RETRY_BASE_S * (2 ** (attempt - 1)))
        continue

    return await _fail(..., error_class, error_message, attempt=attempt)
```

最多重试两次，等待时间是 2 秒、4 秒。也就是说一个抖动型错误最多多等 6 秒。再多就开始影响交互体验。

为什么 `timeout` 不重试？因为超时往往意味着命令本身不适合继续等，或者外部进程卡住了。重复跑一次可能制造更多副作用。`runtime_error` 和 `rate_limited` 更像临时抖动，才进入重试。
