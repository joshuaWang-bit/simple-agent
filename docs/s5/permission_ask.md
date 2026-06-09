# ASK：用 Future 挂起当前工具调用

静态规则如果返回 `ALLOW` 或 `DENY`，`PermissionManager` 可以直接返回。但如果结果是 `ASK`，就要暂停当前工具调用，等用户回应。

这件事靠 `asyncio.Future` 完成：

```python
# core/permissions/manager.py（节选）

future: asyncio.Future[str] = loop.create_future()
self._pending[tool_use_id] = _PendingRequest(
    future=future,
    session_id=session_id,
    tool_name=tool_name,
)

await event_emitter({
    "type": "permission.requested",
    "tool_use_id": tool_use_id,
    "tool_name": tool_name,
    "params": params,
    "param_preview": param_preview(tool_name, params),
    "session_id": session_id,
    "ts": _now(),
})

raw = await asyncio.wait_for(future, timeout=self._timeout_s)
allowed = self._apply_response(raw, session_id, tool_name)
return allowed, raw
```

`await future` 会暂停当前协程，但不会卡死 daemon。事件循环还能继续处理 socket 消息、TUI 事件、其他客户端请求。等用户决定回来，`respond()` 找到对应 Future：

```python
def respond(self, tool_use_id: str, decision: str) -> None:
    req = self._pending.pop(tool_use_id, None)
    if req is None:
        logger.warning("permission.respond: unknown tool_use_id=%s", tool_use_id)
        return
    if not req.future.done():
        req.future.set_result(decision)
```

`future.set_result(decision)` 唤醒刚才挂起的工具调用，`invoke_tool()` 才会继续往下走。

> 💡 这里用 Future，而不是 Queue，是因为权限审批是一对一关系：一个 `tool_use_id` 对应一个用户决定。`_pending[tool_use_id] = future` 刚好表达这个匹配关系。

超时也在这里处理。如果用户长时间不回应，`wait_for` 抛出 `TimeoutError`，manager 返回拒绝，工具不会执行。
