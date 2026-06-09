# 验证

## 手动验证 skill

```bash
uv run kama-core
uv run kama-tui
```

在 TUI 输入：

```text
/review KamaClaude/src/kama_claude/core/loop.py
```

看事件流里是否出现 `skill.invoked`，并确认这次 run 使用的是 review skill 允许的工具。

## 手动验证 subagent

```text
/orchestrate 对 KamaClaude/src/kama_claude/core/runner.py 做一次重构风险分析
```

TUI 应该能看到子 agent 开始和结束事件，子 agent 工具调用会有缩进或层级提示。`~/.kama/sessions/<sid>/runs/` 下也会出现子 run 的 `events.jsonl`。

## 手动验证 MCP

在 `~/.kama/config.toml` 配置一个 MCP server，重启 daemon，观察日志中 server connected 和 discovered tools。然后让 agent 使用对应 `server__tool` 名称的工具。
