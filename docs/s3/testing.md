# 验证

## 手动验证

```bash
# 终端 A：启动 daemon
uv run kama-core

# 终端 B：跑一次任务
uv run kama run --goal "用一句话介绍你自己"

# 终端 C：查看时间线
uv run kama trace
```

核心断言——时间线里应该能看到五种 direction 的记录，按时间顺序依次出现：

```
CLIENT→CORE  command     method=event.subscribe
CORE→CLIENT  response    ...
CLIENT→CORE  command     method=agent.run
CORE         event       type=run.started
CORE→CLIENT  response    run_id=...
CORE→CLIENT  push        event=run.started
CORE→LLM     api_call    msgs=3  tools=1
LLM→CORE     api_response  stop=end_turn  latency=...ms
CORE         event       type=run.finished
CORE→CLIENT  push        event=run.finished
```

如果看到 `CORE→LLM api_call` 之后紧跟 `LLM→CORE api_response(stop=tool_use)`，说明 LLM 请求了工具调用——能和 `events.jsonl` 里的 `tool.call_started` 对应上，两个文件互相印证。

## 验证 include_payload

```bash
# 在 config.toml 里设置 include_llm_payload = true，跑一次任务后：
uv run kama trace --raw | jq 'select(.kind == "api_call") | .data.messages | length'
# 应该输出消息数量（如 3），而不是 null
```
