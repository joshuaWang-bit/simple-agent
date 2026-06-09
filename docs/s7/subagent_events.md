# 子 Agent 的事件怎么回到 TUI

子 agent 有自己的 `child_bus`，但 TUI 订阅的是父 run 的事件流。要让 TUI 看到子 agent 的 token 和工具调用，需要事件桥：

```python
child_bus = EventBus()

async def _bridge(event: BaseModel) -> None:
    await self._parent_bus.publish(event)

child_bus.subscribe(_bridge)
```

子 agent 自己的事件先发布到 `child_bus`，再由 `_bridge` 重新发布到父 bus。父 bus 上的 IPC broadcaster 会把事件推给 TUI。

同时，父 bus 还会发布专门的子 agent 生命周期事件：

```python
await self._parent_bus.publish(
    SubagentStartedEvent(
        run_id=child_run_id,
        parent_run_id=self._parent_run_id,
        description=p.description,
        ts=_now(),
    )
)
```

结束时发布 `SubagentFinishedEvent`。TUI 用这些事件做缩进和层级显示：哪个 run 是父 run，哪个 run 是子 run。

## 事件桥结构

```
Child AgentLoop          child_bus / EventBus          parent_bus / SpawnAgentTool              TUI
    │                            │                                  │                              │
    ├── llm.token ───────────────┤                                  │                              │
    ├── tool.call_started ───────┤                                  │                              │
    └── tool.call_finished ──────┤                                  │                              │
                                 │                                  │                              │
                                 ├── 订阅写入 ──→ EventWriter        │                              │
                                 │     (runs/<run_id>/events.jsonl)  │                              │
                                 │                                  │                              │
                                 └── 订阅转发 ──→ _bridge ───────────┤                              │
                                                                    │                              │
                                 SubagentStartedEvent ──────────────┤                              │
                                 SubagentFinishedEvent ─────────────┤                              │
                                                                    ├── 发布 ──→ IpcEventBroadcaster │
                                                                    │              (socket 推送)     │
                                                                    └──────────────────────────────┴──→ TUI 事件流
```

`child_bus` 隔离子 Agent 内部事件；`_bridge` 选择性转发到 `parent_bus`；TUI 始终只订阅 `parent_bus`。

前台子 agent 会一直跑到结束，然后把 `child_context.result` 包成 `ToolResult` 返回给父 LLM。父 LLM 再根据结果决定下一步，比如派生 executor。

---

# 后台子 Agent 与 agent_result

有些子任务可以并行。比如 planner 拆出三个互不相关的代码区域，父 agent 可以同时派生三个 reviewer。

这时 `spawn_agent` 可以设置：

```json
{"run_in_background": true}
```

后台模式下，工具不会等待子 agent 完成：

```python
task = asyncio.create_task(
    self._run_background(child_loop, child_context, child_bus, ...)
)
self._task_registry.register(child_run_id, task, child_context)
return ToolResult(
    content=(
        f"Subagent started in background. run_id={child_run_id}. "
        f"Use agent_result(run_id='{child_run_id}') to retrieve result."
    )
)
```

`BackgroundTaskRegistry` 保存 `run_id → (asyncio.Task, ExecutionContext)`。父 agent 后面调用 `agent_result(run_id=...)`：

```python
if not task.done():
    return ToolResult(content="still running")
if task.cancelled():
    return ToolResult(content="Subagent was cancelled.", is_error=True)
exc = task.exception()
if exc is not None:
    return ToolResult(content=f"Subagent raised an exception: {exc}", is_error=True)
return ToolResult(content=context.result or "Subagent completed with no text result.")
```

`task.done()` 是非阻塞检查。父 agent 可以继续做别的事，隔一会再查询结果。

注意：后台子 agent 的事件仍然通过 bridge 推给 TUI。父 agent 不等待它，不代表用户看不到它。
