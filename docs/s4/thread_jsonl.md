# thread.jsonl：完整回放，而不是最近 K 轮

`SessionStore.read_messages` 读出来的不是给人看的日志，而是可以直接发给 Anthropic API 的 messages：

```python
# src/simple_agent/core/session/store.py（节选）

def read_messages(self, sid: str) -> list[dict[str, Any]]:
    path = self.session_dir(sid) / "thread.jsonl"
    if not path.exists():
        return []

    messages = []
    for line_no, line in enumerate(path.read_text().splitlines(), start=1):
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("skip broken thread row sid=%s line=%s", sid, line_no)
            continue
        role = row.get("role")
        if role not in ("user", "assistant"):
            continue
        messages.append({"role": role, "content": row.get("content", "")})

    return self._trim_orphan_tool_use(messages)
```

注意最后返回前调用了 `_trim_orphan_tool_use`。Anthropic 的消息格式要求 `tool_use` 后面必须有匹配的 `tool_result`。如果某次 run 在工具调用中途崩了，thread 里可能留下半截 `tool_use`。下次读取时把孤儿 `tool_use` 裁掉，可以避免 API 直接报 `messages.invalid`。

第一轮结束后，`thread.jsonl` 可能长这样：

```json
{"role":"user","content":"项目用什么 Python 版本？"}
{"role":"assistant","content":[
  {"type":"text","text":"我先看 pyproject.toml。"},
  {"type":"tool_use","id":"toolu_01","name":"read_file","input":{"path":"pyproject.toml"}}
]}
{"role":"user","content":[
  {"type":"tool_result","tool_use_id":"toolu_01","content":"requires-python = \">=3.12\""}
]}
{"role":"assistant","content":[
  {"type":"text","text":"项目使用 Python 3.12。"}
]}
```

s4 的选择是：**每次新 run 启动时完整回放整个 thread，不做最近 K 轮截断。**
