# 三层 context：把稳定背景放进 system prompt

s4 已经有 `notes.md`。它是 agent 在当前 session 里通过 `note_save` 主动保存的事实。s6 新增两层用户可维护的 context：

```text
~/.kama/context.md
.kama/context.md
```

这两个文件就是普通 Markdown。没有数据库，没有向量检索，也没有同步后台任务。s6 要的是一个可解释、可编辑、可调试的上下文层。

## 读取函数很薄

```python
# core/memory/loader.py

def load_context_file(path: Path) -> str:
    p = path.expanduser()
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8").strip()
```

## 接入点在 AgentRunner

```python
# core/runner.py（节选）

if session is not None and store is not None:
    history = store.read_messages(session.id)
    notes = store.read_notes(session.id)
else:
    history = [{"role": "user", "content": goal}]
    notes = ""

global_ctx = load_context_file(Path("~/.kama/context.md").expanduser())
project_ctx = load_context_file(Path(".kama/context.md"))

context = ExecutionContext(
    run_id=run_id,
    goal=goal,
    prefill_messages=history,
    session_notes=notes,
    global_context=global_ctx,
    project_context=project_ctx,
)
```

这些内容不追加到 `messages`，而是拼进 system prompt：

```python
def system_prompt(self, base: str) -> str:
    parts = [base]
    if self.global_context.strip():
        parts.append("\n\n## Global Context\n" + self.global_context.strip())
    if self.project_context.strip():
        parts.append("\n\n## Project Context\n" + self.project_context.strip())
    if self.session_notes.strip():
        parts.append("\n\n## Session Notes\n" + self.session_notes.strip())
    return "".join(parts)
```

## 为什么放 system，不放 thread？

因为这些不是某一轮用户消息。`~/.kama/context.md` 可能是用户长期偏好，`.kama/context.md` 可能是项目目录约定，`notes.md` 是会话事实层。它们都是工作背景。放进 system prompt，语义更准确，也不会污染 `thread.jsonl`。

一个项目级 context 可以这样写：

```markdown
# KamaClaude
- Source root: KamaClaude/src/kama_claude/
- Tests live in KamaClaude/tests/
- Prefer focused unit tests for changed core behavior.
- Do not rewrite unrelated tutorial sections.
```

下一次用户只说"补一下相关测试"，agent 也能知道测试目录在哪里。
