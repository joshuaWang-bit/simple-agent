# 跑起来

## 项目目录结构（s1 完成时）

```
simple-agent/
├── pyproject.toml
├── src/
│   └── simple_agent/
│       ├── __init__.py
│       ├── cli/
│       │   ├── __init__.py
│       │   ├── main.py
│       │   └── commands/
│       │       ├── __init__.py
│       │       ├── ping.py
│       │       └── run.py          # 新增
│       └── core/
│           ├── __init__.py
│           ├── app.py
│           ├── config.py
│           ├── context.py           # 新增
│           ├── loop.py              # 新增
│           ├── runner.py            # 新增
│           ├── bus/
│           │   ├── __init__.py
│           │   ├── commands.py
│           │   ├── envelope.py
│           │   └── events.py
│           ├── events/              # 新增
│           │   ├── __init__.py
│           │   ├── bus.py
│           │   ├── types.py
│           │   └── writer.py
│           ├── llm/                 # 新增
│           │   ├── __init__.py
│           │   └── provider.py
│           ├── printer.py           # 新增
│           └── tools/               # 新增
│               ├── __init__.py
│               ├── base.py
│               ├── invoke.py
│               ├── read_file.py
│               └── registry.py
```

## 运行

```bash
# 设置 API Key（硅基流动）
export WIKI_LLM_SILICONFLOW_API_KEY=sk-...

# 执行
uv run sagent run --goal "总结 README.md 的主要章节"

# 使用 ultra 档次模型
uv run sagent run --goal "总结 README.md 的主要章节" --tier ultra
```

终端输出：

```
[run] 20260511-161020-abc123
[step 1] planning...
I'll read the README.md file to get its contents.
[tool] read_file {"path": "README.md"}
[tool] read_file ✓  4ms
[step 1] done
[step 2] planning...
# Summary
The README covers the following sections...
[step 2] done
[run] success  2 steps  5.3s
```

## events.jsonl

运行结束后，`runs/20260511-161020-abc123/events.jsonl` 里会留下完整记录：

```json
{"type":"run.started","run_id":"20260511-161020-abc123","goal":"总结 README.md 的主要章节","ts":"2026-05-11T16:10:20.001Z"}
{"type":"step.started","run_id":"20260511-161020-abc123","step":1,"ts":"2026-05-11T16:10:20.002Z"}
{"type":"llm.request","run_id":"20260511-161020-abc123","model":"claude-sonnet-4-20250514","ts":"2026-05-11T16:10:20.003Z"}
{"type":"llm.token","run_id":"20260511-161020-abc123","token":"I'll read the README.md file to get its contents.","ts":"..."}
{"type":"tool.call_started","run_id":"20260511-161020-abc123","tool_use_id":"toolu_01...","tool_name":"read_file","input":{"path":"README.md"},"ts":"..."}
{"type":"tool.call_finished","run_id":"20260511-161020-abc123","tool_use_id":"toolu_01...","tool_name":"read_file","elapsed_ms":4,"ts":"..."}
{"type":"step.finished","run_id":"20260511-161020-abc123","step":1,"status":"running","ts":"..."}
...
{"type":"run.finished","run_id":"20260511-161020-abc123","status":"success","step_count":2,"elapsed_s":5.3,"ts":"..."}
```

每一行是一个独立的事件，可以用 `jq` 或 `cat events.jsonl | python -m json.tool --json-lines` 查看。
