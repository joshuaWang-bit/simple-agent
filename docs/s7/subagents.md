# spawn_agent：派生一个干净的子 Agent

父 agent 拿到 orchestrate prompt 后，会调用 `spawn_agent`：

```json
{
    "description": "规划重构",
    "subagent_type": "planner",
    "prompt": "分析 core/runner.py 的影响范围，只读，不要修改文件"
}
```

`SpawnAgentTool` 的参数模型：

```python
class SpawnAgentParams(BaseModel):
    description: str
    prompt: str
    run_in_background: bool = False
    subagent_type: str = ""
```

## 创建隔离的子 agent

真正创建子 agent 时，它会生成新的 run_id、新的 ExecutionContext、新的 EventBus：

```python
child_run_id = new_run_id()
child_context = ExecutionContext(
    run_id=child_run_id,
    goal=p.prompt,
    max_steps=self._max_steps,
    system_prompt_override=profile.system_prompt if profile else None,
)

child_bus = EventBus()
child_registry = self._build_child_registry(child_bus, child_run_id, profile)
child_loop = AgentLoop(self._provider, child_registry, child_bus, ...)
```

**最重要的一点：子 agent 不继承父 agent 的 messages 历史。**

它的上下文只有 `prompt` 变成的那条 user 消息，加上角色配置里的 system prompt。父 agent 如果希望子 agent 知道某个文件路径、约束、目标，就必须写进 `prompt`。

这是一种隔离。子任务越明确，子 agent 越不容易被父级对话里的无关内容干扰。

## 嵌套深度限制

`SpawnAgentTool` 还限制最大嵌套深度：

```python
if self._depth >= 2:
    return ToolResult(
        content="Subagent nesting limit (2) reached; cannot spawn further subagents.",
        is_error=True,
    )
```

没有这个限制，LLM 可能不断派生子 agent，形成不可控的递归。

> 💡 子 agent 复用同一个 provider 实例，但 messages 是隔离的。连接和客户端对象可以复用，认知上下文不能混在一起。

---

# 角色配置：planner、executor、reviewer

`subagent_type="planner"` 会触发 `AgentProfileLoader` 查找角色配置：

```toml
[agent]
description = "规划 agent：分析目标并拆解任务"
system_prompt = """
你是规划专家。只分析和拆解，不修改文件。
"""
allowed_tools = ["read_file", "list_dir", "task_create", "task_update"]
```

## 三级查找

角色配置也是三级查找：

```text
.kama/agents/<name>.toml
~/.kama/agents/<name>.toml
内建 core/agents/builtin/<name>.toml
```

## 子 agent 工具过滤

子 agent registry 按角色 `allowed_tools` 过滤：

```python
allowed = set(profile.allowed_tools) if profile and profile.allowed_tools else None

def _allowed(name: str) -> bool:
    return allowed is None or name in allowed

for t in [ReadFileTool(), BashTool(), WriteFileTool(), ListDirTool()]:
    if _allowed(t.name):
        registry.register(t)
```

## 三个典型角色的边界

| 角色 | 主要职责 | 工具边界 |
|------|----------|----------|
| planner | 读上下文、拆任务、制定计划 | 只读和 task 工具 |
| executor | 按计划修改代码、运行测试 | bash/read/write/list/task |
| reviewer | 复查结果、指出风险 | 只读查询，尽量不写 |

这不是纯 prompt 约束。工具白名单让 planner 根本拿不到 `write_file`，系统层面降低越界概率。
