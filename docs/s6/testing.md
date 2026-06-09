# 验证

```bash
uv run kama-core
uv run kama chat
```

准备一个项目 context：

```bash
mkdir -p .kama
cat > .kama/context.md <<'EOF'
# Project Context
- Tests live in KamaClaude/tests/
- Prefer focused unit tests.
EOF
```

让 agent 问一个依赖项目约定的问题，确认它能看到这段 context。然后制造一个长工具输出，例如让它读取或 grep 一个大文件，观察 TUI 的 `tokens ... context` 行。

手动 compact：

```text
/compact 保留当前任务目标、已修改文件和剩余 TODO
```

检查 session 目录：

```bash
ls ~/.kama/sessions/sess-*/
# thread.jsonl
# thread_*.jsonl.bak
# summary_*.md
```
