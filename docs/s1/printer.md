# StdoutPrinter：终端实时输出

`StdoutPrinter` 是 EventBus 的一个订阅者，负责把事件格式化成人类可读的文本，实时打印到终端。

```python
# core/printer.py（节选）

class StdoutPrinter:
    def handle(self, event: BaseModel) -> None:
        match event.type:
            case "run.started":
                print(f"[run] {event.run_id}")
            case "step.started":
                print(f"[step {event.step}] planning...")
            case "llm.token":
                print(event.token, end="", flush=True)
            case "tool.call_started":
                print(f"\n[tool] {event.tool_name} {event.input}")
            case "tool.call_finished":
                print(f"[tool] {event.tool_name} ✓  {event.elapsed_ms}ms")
            case "step.finished":
                print(f"\n[step {event.step}] done")
            case "run.finished":
                status = "success" if event.status == "success" else event.reason
                print(f"[run] {status}  {event.step_count} steps  {event.elapsed_s:.1f}s")
```

`handle()` 用 `match` 语句（Python 3.10+ 的 `structural pattern matching`）根据事件类型分发到不同的输出格式。这样新增事件类型时，只需要再加一个 `case` 分支，不需要改现有逻辑。

`llm.token` 事件直接 `print(token, end="", flush=True)`，实现打字机效果。其他事件换行输出，保持终端整洁。
