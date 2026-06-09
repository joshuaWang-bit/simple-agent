# 斜杠命令：把用户输入变成工作流

用户输入 `/orchestrate ...` 后，消息仍然走 s4 的 `session.send_message`。第一个变化点在 `SessionManager.send_message()`：

```python
# core/session/manager.py（节选）

goal = content
system_prompt_override: str | None = None
tool_whitelist: list[str] | None = None

if content.startswith("/"):
    parts = content[1:].split(None, 1)
    skill_name = parts[0]
    arguments = parts[1] if len(parts) > 1 else ""
    skill = self._skill_loader.resolve(skill_name)
    if skill is not None:
        goal = self._skill_loader.render_prompt(skill, arguments)
        system_prompt_override = skill.system_prompt_template
        tool_whitelist = skill.allowed_tools or None
        await self._bus.publish(SkillInvokedEvent(...))
```

找不到 skill 时，输入会被当作普通用户消息。找到了，`goal` 会变成渲染后的 skill prompt，`system_prompt_override` 和 `tool_whitelist` 一起传给 runner。

## skill 文件格式

skill 文件是带 frontmatter 的 Markdown：

```markdown
---
name: orchestrate
description: 用 planner → executor → reviewer 工作流完成复杂任务
allowed_tools:
  - spawn_agent
  - agent_result
  - task_create
  - task_update
  - task_list
---

你是 multi-agent 协调者。请完成以下目标：

$ARGUMENTS

请先派生 planner，再根据计划派生 executor，最后派生 reviewer。
```

## SkillLoader 很克制

```python
def render_prompt(self, skill: Skill, arguments: str) -> str:
    return skill.system_prompt_template.replace("$ARGUMENTS", arguments)
```

skill 本质上是一个可复用的 system prompt 模板，再加一份工具白名单。

## 查找顺序三级

```text
.kama/skills/<name>.md
~/.kama/skills/<name>.md
内建 core/skills/builtin/<name>.md
```

项目本地优先，方便一个仓库覆盖内建 `/review` 或新增自己的 `/deploy`。

---

# 工具白名单：协调者不能越界

`SessionManager` 把 `tool_whitelist` 传给 `AgentRunner.run_and_capture()`。runner 构造 registry 时，每个工具都要过一遍 `_ok()`：

```python
allowed: set[str] | None = set(tool_whitelist) if tool_whitelist else None

def _ok(name: str) -> bool:
    return allowed is None or name in allowed

for t in [ReadFileTool(), BashTool(), WriteFileTool(), ListDirTool()]:
    if _ok(t.name):
        registry.register(t)
```

这不是在 prompt 里劝 LLM "不要用 bash"，而是 registry 里根本不给它 bash。LLM 看不到工具 schema，自然无法调用。

对 `/orchestrate` 来说，父 agent 的角色是协调者。它应该拆任务、派生子 agent、收集结果，而不是自己读文件或改代码。所以它的白名单里有 `spawn_agent`、`agent_result`、任务工具，没有 `read_file`、`bash`、`write_file`。

## system_prompt_override

`system_prompt_override` 则替换默认 system prompt：

```python
def system_prompt(self, base: str) -> str:
    parts = [self.system_prompt_override if self.system_prompt_override else base]
    ...
    return "".join(parts)
```

为什么是覆盖，不是追加？因为默认 prompt 和 skill prompt 可能定义不同身份。一个说"你是通用助手"，另一个说"你是协调者"，追加会制造冲突。
