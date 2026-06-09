# 验证

## 单元测试

```bash
uv run pytest tests/unit/test_permission_policy.py \
             tests/unit/test_permission_manager.py \
             tests/unit/test_tool_retry.py \
             tests/unit/test_tool_params.py -v
```

重点看几类用例：

- `outside-cwd` 命中后即使有 allow pattern 也必须 `ASK`。
- `PermissionManager.respond()` 能唤醒等待中的 Future。
- `always allow` / `deny` 会命中缓存，并写入 policy 文件。
- `runtime_error` 和 `rate_limited` 会重试，`schema_error`、`timeout`、`permission_denied` 不重试。

## 手动验证

```bash
uv run kama-core
uv run kama-tui
```

在 TUI 输入框里让 agent 执行一个 bash 命令，例如：

```text
用 bash 列出当前目录
```

应该看到审批卡片。按 `y` 放行，工具继续执行；按 `n` 拒绝，LLM 收到 `permission_denied` 的 tool result。

再试一个越界命令：

```text
用 bash 查看 /etc/hostname
```

即使你之前选择过 always allow bash，也应该再次弹出审批。这个验证的是 s5 的安全底线：**越界操作不可被缓存静默绕过。**
