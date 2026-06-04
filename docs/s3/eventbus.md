# 埋点 ③：EventBus 层——CoreApp 订阅者

CoreApp.run() 里，trace 作为 EventBus 的普通订阅者挂上去，和 EventWriter、IpcEventBroadcaster 并列：

```python
# core/app.py（节选）

async def _trace_event_handler(self, event: BaseModel) -> None:
    assert self._trace is not None
    event_dict = event.model_dump()
    self._trace.emit(
        TraceRecord(
            ts=_now(),
            direction="CORE",
            layer="event",
            kind="event",
            run_id=event_dict.get("run_id"),
            data=event_dict,
        )
    )

# run() 里：
self._bus.subscribe(self._trace_event_handler)
```

EventBus 本身不需要改动——trace 只是又一个订阅者。这个设计让 EventBus 保持对 trace 系统的完全无感知，也让 `_trace_event_handler` 可以单独测试和替换，不影响其他订阅者。
