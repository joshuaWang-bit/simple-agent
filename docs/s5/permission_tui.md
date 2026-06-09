# permission 事件怎么到 TUI

`PermissionManager` 本身不认识 TUI。它只调用传进来的 `event_emitter`。

在 `invoke_tool()` 里，这个 emitter 把原始 dict 包成 pydantic 事件并发到 `EventBus`：

```python
async def _emit_permission(raw: dict[str, Any]) -> None:
    await bus.publish(PermissionRequestedEvent(**raw, run_id=run_id))

allowed, decision = await permission_manager.check_and_wait(
    tool_use_id=tool_call.id,
    tool_name=tool_call.name,
    params=dict(tool_call.input),
    session_id=session_id,
    event_emitter=_emit_permission,
)
```

s2 建好的 IPC broadcaster 已经订阅了全局 `EventBus`，所以 `permission.requested` 会像 `llm.token`、`tool.call_started` 一样推给所有客户端。

用户决定的反方向是一条 IPC 命令：

```python
# core/app.py（节选）

async def _permission_respond_handler(self, params):
    cmd = PermissionRespondCommand.model_validate(params)
    self._permission_manager.respond(cmd.tool_use_id, cmd.decision)
    return PermissionRespondResult()
```

这条链路合起来就是：

```
invoke_tool
    → permission.requested event
    → IpcEventBroadcaster
    → TUI
    → permission.respond command
    → PermissionManager.respond()
    → Future resolve
    → invoke_tool 继续
```

---

# TUI：审批卡片不能阻塞消息泵

TUI 收到 `permission.requested` 后会做两件事：

```python
elif t == "permission.requested":
    perm_block = PermissionBlock(tool_use_id, tool_name, param_preview)
    self._pending_permission_blocks[tool_use_id] = perm_block
    self._append(perm_block)

    select = PermissionSelect(tool_use_id)
    self._mount_permission_select(select)
```

`PermissionBlock` 是日志流里那张卡片，负责显示工具名、参数摘要和最终结果。`PermissionSelect` 是真正接收键盘的控件，支持 `y/a/n/d` 或上下选择后回车。

## s5 调试出来的坑：Textual 消息泵不能长时间 await

这里有一个 s5 调试出来的坑：Textual 的消息处理函数不能长时间 `await`。

s4 的 TUI 输入框提交后，如果直接：

```python
await self._client.send_command("session.send_message", ...)
```

这个 `await` 会等整个 agent run 完成。run 期间如果出现权限请求，TUI 要挂载 `PermissionSelect`，但消息泵被上面的 `await` 占着，焦点切不过来，用户按键没有反应。

修复方式是把 `send_message` 放进 worker：

```python
async def on_chat_text_area_submitted(self, event):
    self.run_worker(
        self._do_send_message(content),
        name="send_message",
        exclusive=False,
    )
```

`run_worker` 让长时间运行的 socket 请求在独立任务里跑，Textual 消息泵保持畅通。这样 `PermissionSelect.on_mount()` 里的 `focus()` 才能生效。

> ⚠️ UI 里的 `await` 不只是"等待"，它可能阻塞整个事件分发。涉及 agent run 这种长任务，要放进 worker。
