# 验证

启动 daemon：

```bash
uv run sagent-core
```

另一个终端启动 TUI：

```bash
uv run sagent-tui
```

TUI 底部输入框就绪后，依次发送两条消息：

```
项目的 Python 版本是多少？看 pyproject.toml
```

等 agent 回答完成、输入框重新激活，再发：

```
写一个适合该版本的新特性 demo 到 /tmp/demo.py
```

然后看 session 目录：

```bash
ls ~/.sagent/sessions/sess-*/
# meta.json  notes.md  thread.jsonl  runs/

cat ~/.sagent/sessions/sess-*/notes.md

cat ~/.sagent/sessions/sess-*/thread.jsonl | python -c "
import json, sys
for line in sys.stdin:
    msg = json.loads(line)
    print(msg['role'], '|', str(msg['content'])[:120])
"
```

验收点不是"目录存在"这么简单，而是三件事：

- `thread.jsonl` 里有完整的 `tool_use` / `tool_result` 块，不只是最终文本。
- `notes.md` 里有 agent 通过 `note_save` 写下的关键事实。
- 第二轮 run 不需要重新读取 `pyproject.toml` 来理解"该版本"。

可以检查第二个 run 的事件：

```bash
cat ~/.sagent/sessions/sess-*/runs/<run-2-id>/events.jsonl | grep '"tool_name":"read_file"'
```

如果这里又出现读取 `pyproject.toml`，说明记忆没有真正生效；如果它直接写 demo 或回答，说明 thread + notes 的路径跑通了。
