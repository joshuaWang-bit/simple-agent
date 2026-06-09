# PermissionManager：静态规则先判断

参数合法之后，才进入权限层。

权限规则分两部分：`policy.py` 负责纯同步评估，`manager.py` 负责缓存、事件、Future 等异步流程。

## 静态评估的核心 evaluate()

```python
# core/permissions/policy.py（节选）

def evaluate(tool_name: str, params: dict[str, Any], policy: ToolPolicy | None = None):
    if policy is None:
        policy = DEFAULT_POLICIES.get(tool_name)
    if policy is None:
        return PermissionDecision.ASK

    command = str(params.get("command", "")) if tool_name == "bash" else ""

    if command:
        for pat in policy.deny_patterns:
            if re.search(pat, command):
                return PermissionDecision.DENY

    if command and matches_outside_cwd(command):
        return PermissionDecision.ASK

    if command:
        for pat in policy.allow_patterns:
            if re.search(pat, command):
                return PermissionDecision.ALLOW

    return policy.default
```

评估顺序是：**deny → outside-cwd → allow → default**。任何一步命中就直接返回，不再往后走。

## 默认策略很保守

```python
DEFAULT_POLICIES = {
    "bash":       ToolPolicy(default=PermissionDecision.ASK),
    "write_file": ToolPolicy(default=PermissionDecision.ASK),
    "read_file":  ToolPolicy(default=PermissionDecision.ALLOW),
    "list_dir":   ToolPolicy(default=PermissionDecision.ALLOW),
    "note_save":  ToolPolicy(default=PermissionDecision.ALLOW),
}
```

有副作用的工具默认问用户；只读工具和 `note_save` 默认放行。

## outside-cwd：越界不等于危险，但必须让用户知道

这里最关键的是 `matches_outside_cwd()`。它检测 bash 命令里是否有明显越界操作：

```python
OUTSIDE_CWD_HEURISTICS = [
    r"(^|\s)/[^\s]",               # absolute path
    r"(^|\s)~",                    # home path
    r"(^|\s)\.\.(/|$|\s)",         # parent traversal
    r"\$\{?HOME\b",
    r"\$\{?PWD\b",
    r"(^|\s|;|&&|\|\|)cd(\s|$)",
]
```

这些命中后不是直接 `DENY`，而是强制 `ASK`。

为什么不直接拒绝？因为 `/etc/hostname`、`~/Downloads/log.txt`、`../other-project/README.md` 都可能是合理读取。越界不等于危险，但越界必须让用户知道。

为什么 outside-cwd 要放在 `allow_patterns` 前面？因为它是安全底线。就算用户配置了 `allow_patterns = [".*"]`，`bash cat ~/.ssh/config` 也不能静默通过。
