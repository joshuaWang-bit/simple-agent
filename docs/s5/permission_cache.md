# always 决策：session 缓存与持久化策略

TUI 里用户不只有"允许一次"和"拒绝一次"，还有 `"always allow"` / `"always deny"`。

`_apply_response()` 会同时写两层缓存：

```python
def _apply_response(self, decision: str, session_id: str, tool_name: str) -> bool:
    allow = decision in ("allow_once", "always_allow")
    if decision == "always_allow":
        self._session_always[(session_id, tool_name)] = "allow"
        self._persistent_always[tool_name] = "allow"
        if self._policy_file is not None:
            save_policy_file(self._persistent_always, self._policy_file)
    elif decision == "always_deny":
        self._session_always[(session_id, tool_name)] = "deny"
        self._persistent_always[tool_name] = "deny"
        if self._policy_file is not None:
            save_policy_file(self._persistent_always, self._policy_file)
    return allow
```

- **session 缓存**：让同一个会话内不重复问。
- **持久化缓存**：让用户下次启动 daemon 后仍然保留 `"always"` 选择。

## outside-cwd 不会被缓存绕过

但有一个边界不变：**outside-cwd 强制 ASK 不会被缓存绕过。**

`check_and_wait()` 会先检查 deny pattern，再判断 outside-cwd。只有没有命中 outside-cwd 时，才看 session cache 和 persistent cache。这保证了用户哪怕长期允许 `bash`，越界 `bash` 仍然要问。
