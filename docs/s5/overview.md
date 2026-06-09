# S5-给工具加上安全锁

## 第 5 阶段：给工具加上安全锁

| 项目 | 内容 |
|------|------|
| 阶段 | s5 |
| 分支 | `stage/s5` |
| 参考 Tag | `v5.0.0` |
| 本阶段新增 | 工具权限审批、TUI 内联审批卡片、pydantic 参数校验、失败分类与指数退避重试 |
| 依赖上一阶段 | s4 的 Session、AgentRunner、AgentLoop、IPC 事件流和 TUI 输入框 |

## 本阶段要做什么

s4 之后，agent 已经能持续对话，也能记住上一轮发生过什么。这个能力一旦接上 s3 的工具集，就会暴露一个更尖锐的问题：**agent 能直接执行有副作用的工具。**

比如用户说：

```text
清理一下临时文件
```

LLM 可能调用：

```json
{"name":"bash","input":{"command":"rm -rf /tmp/kama-old"}}
```

也可能在理解错目录时调用：

```json
{"name":"bash","input":{"command":"rm -rf ~/.cache"}}
```

s4 的工具调用路径没有任何审批：

```python
result = await invoke_tool(self._registry, tc, self._bus, context.run_id)
```

`invoke_tool()` 找到工具就执行。读文件、写文件、跑 bash、保存 note，在调用层面没有区别。

s5 要把这条路径补完整：工具执行前先做参数校验，再做权限判断；需要问用户时，daemon 暂停当前工具调用，TUI 插入审批卡片，用户按键后再继续。工具执行失败后，也不能再只有一个模糊的"失败"，而要分清是参数错、权限拒绝、超时、运行时错误，还是上游限速。

这章就顺着一次 `bash` 工具调用走：

```
AgentLoop
    ↓
invoke_tool()
    ↓
pydantic 参数校验 ──失败──→ schema_error
    ↓
PermissionManager.check_and_wait()
    ├── ALLOW ──→ tool.invoke ──→ ToolResult
    ├── DENY  ──→ permission_denied
    └── ASK   ──→ permission.requested 事件
                      ↓
                 TUI 审批
                      ↓
                 permission.respond
                      ↓
                 Future.resolve
                      ↓
                 invoke_tool 继续
                      ↓
              真正执行工具
                      ↓
              失败分类 / 重试
                      ↓
              tool result 回到 LLM
```

ASK 路径的核心是：**daemon 挂起 `invoke_tool`，TUI 审批后 `Future.resolve` 恢复执行。** 整个过程中事件循环不被阻塞，其他消息和事件照常处理。
