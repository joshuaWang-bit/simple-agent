# CoreApp 串联

CoreApp.run() 是把所有组件接在一起的地方：

```python
# core/app.py (run() 节选)

if self._config.trace.enabled:
    trace_path = Path(self._config.trace.file).expanduser()
    self._trace = TraceWriter(trace_path)
    await self._trace.start()
    self._bus.subscribe(self._trace_event_handler)   # 埋点 ③

self._broadcaster = IpcEventBroadcaster(trace=self._trace)   # 埋点 ②

server = SocketServer(
    self._config.host, self._config.port,
    self._broadcaster,
    trace=self._trace,   # 埋点 ①
)
```

runner 创建时注入 trace：

```python
runner = AgentRunner(self._config, bus=self._bus, trace=self._trace)   # 埋点 ④
```

关闭时等队列清空：

```python
await server.stop()
if self._trace is not None:
    await self._trace.stop()
```

三个埋点（IPC 层两处 + EventBus 层）通过构造函数注入 `TraceWriter`；LLM 层埋点通过 `AgentRunner` 的 `trace` 参数在 runner 内部包装。所有组件都收到同一个 `TraceWriter` 实例，写入的是同一个文件，时间顺序由各 `emit()` 调用时的挂钟时间决定。
