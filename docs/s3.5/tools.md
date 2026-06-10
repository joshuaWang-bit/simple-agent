# 工具集扩展到 8 个

s3 的 `ToolRegistry` 里注册了 8 个工具。LLM 在每次 plan 阶段都能看到它们全部的 schema，自主决定使用哪些、按什么顺序。

## 任务工具（4 个）

| 工具 | 作用 |
|------|------|
| `task_create` | 创建新任务，可选设置 `blocked_by` 依赖 |
| `task_update` | 更新状态（pending / in_progress / completed）或调整依赖 |
| `task_list` | 列出所有任务的当前状态，返回格式化摘要 |
| `task_get` | 获取单个任务的完整 JSON |

`task_list` 的返回格式是专为 LLM 设计的紧凑表示：

```
[ ] #1: 分析目录结构
[>] #2: 读取核心模块代码 (blocked by: [])
[x] #3: 分析代码风格
[ ] #4: 写报告 (blocked by: [2, 3])
```

`[ ]` 是 pending，`[>]` 是 in_progress，`[x]` 是 completed。LLM 一眼就能判断哪些任务可以开始、哪些还在等待。

## 执行工具（4 个）

| 工具 | 作用 |
|------|------|
| `read_file` | 读取文件内容，最大 512 KB，自动截断 |
| `write_file` | 写文件，自动创建父目录，阻止路径穿越 |
| `list_dir` | 列出目录结构，可控制递归深度 |
| `bash` | 执行 shell 命令，合并 stdout/stderr，64 KB 输出上限 |

s1 和 s2 只有 `read_file`。s3 加入 `bash`、`write_file`、`list_dir` 之后，agent 能做的事彻底不同了：它可以运行测试、调用命令行工具、写入文件、遍历目录。对于代码分析、文件生成这类任务，这几个工具的组合基本已经够用。

## bash 工具的实现

```python
# core/tools/builtin/bash.py

async def invoke(self, params: dict[str, object]) -> ToolResult:
    p = BashParams.model_validate(params)
    proc = await asyncio.create_subprocess_shell(
        p.command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=p.timeout)
    except TimeoutError:
        proc.kill()
        await proc.communicate()
        return ToolResult(content=f"[timeout after {p.timeout}s]", is_error=True, error_ty
    ...
    if proc.returncode != 0:
        return ToolResult(content=f"[exit {proc.returncode}]\n{output}", is_error=True, ..
    return ToolResult(content=output or "[no output]")
```

`asyncio.create_subprocess_shell` 执行任意 shell 命令，`asyncio.wait_for` 控制超时（默认 60 秒，最大允许 120 秒），超时后 `proc.kill()` 强制终止。非零退出码返回 `is_error=True` 的 `ToolResult`，让 LLM 知道命令失败了。

> **bash 工具的安全边界**
>
> 没有沙箱，没有权限限制——这是 s3 的已知局限，适合本地开发场景，生产部署需要额外的隔离层。
