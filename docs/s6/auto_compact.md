# 自动 compact：当前 run 内续航

自动 compact 的触发点在 `AgentLoop.run()`。它不在每一步开头做，而是在一次 LLM 响应之后检查：

```python
# core/loop.py（节选）

if (
    not context.is_done()
    and response.stop_reason == "tool_use"
    and self._compactor is not None
    and self._compact_threshold > 0
    and response.usage is not None
    and response.usage.context_pct >= self._compact_threshold
):
    await self._compactor.compact(context, self._provider)
```

有几个条件值得看：

- `not context.is_done()`：任务已经结束就没必要 compact。
- `response.stop_reason == "tool_use"`：只有后面还要继续执行工具、继续下一轮时才压缩。
- `self._compact_threshold > 0`：阈值为 0 表示关闭自动 compact。

## 默认关闭

当前配置默认就是关闭：

```python
@dataclass
class CompactionConfig:
    auto_threshold: float = 0.0
    tool_result_limit: int = 8_000
    tool_result_keep: int = 4_000
```

为什么默认不自动 compact？因为 compact 是有损操作。它依赖另一次 LLM 总结历史，摘要再好也可能漏信息。s6 先提供能力和手动入口，自动触发留给明确配置的用户打开。

如果用户想开：

```toml
[compaction]
auto_threshold = 0.80
```
