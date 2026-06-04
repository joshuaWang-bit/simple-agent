# kama trace：查看时间线

`kama trace` 命令从 `daemon.jsonl` 读取记录，彩色输出，可以按 run_id、layer、direction 过滤：

```bash
# 查看所有记录
uv run kama trace

# 只看 LLM 层（发出的请求和收到的响应）
uv run kama trace --layer llm

# 只看某次 run 的记录
uv run kama trace run-20260516-abc123

# 实时跟踪（像 tail -f）
uv run kama trace --follow

# 输出原始 NDJSON，供 jq 处理
uv run kama trace --raw | jq 'select(.direction == "LLM→CORE")'
```

输出格式（按 direction 着色，摘要折叠大字段）：

```
10:00:00.001  CLIENT→CORE  command     method=agent.run  goal="总结 README.md 的主要章节"
10:00:00.003  CORE         event       type=run.started
10:00:00.004  CORE→CLIENT  response    run_id=20260516
10:00:00.005  CORE→CLIENT  push        event=run.started  sub=sub-a1b2c3
10:00:00.009  CORE→LLM     api_call    msgs=3  tools=1
10:00:00.851  LLM→CORE     api_response  stop=tool_use  latency=842ms  out_tokens=47
10:00:00.852  CORE         event       type=tool.call_started
10:00:00.856  CORE         event       type=tool.call_finished
10:00:00.857  CORE→LLM     api_call    msgs=5  tools=1
10:00:01.623  LLM→CORE     api_response  stop=end_turn  latency=766ms  out_tokens=89
10:00:01.624  CORE         event       type=run.finished
10:00:01.625  CORE→CLIENT  push        event=run.finished  sub=sub-a1b2c3
```

`_summarize()` 为每种 kind 定义了不同的摘要逻辑：`command` 记录展示 `method` 和 `goal`，`api_call` 记录展示消息数和工具数，`api_response` 记录展示 `stop_reason`、延迟和 `output_tokens`。大字段（完整的 `messages` 数组）只出现在 `--raw` 模式的原始输出里，命令行浏览时不会被淹没。
