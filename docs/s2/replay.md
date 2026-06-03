# 事件回放

`event.subscribe` 有一个可选参数 `replay_from_run`：

```json
{
  "topics": ["run.*", "step.*", "tool.*"],
  "scope": "global",
  "replay_from_run": "20260515-abc"
}
```

带上这个参数，守护进程在建立实时订阅之前，先从对应的 `events.jsonl` 推送历史事件：

```python
# core/app.py（节选）

async def _replay_events(self, run_id, writer, topics) -> int:
    path = events_file(run_id)   # ~/.kama/runs/<run_id>/events.jsonl
    if not path.exists():
        return 0

    count = 0
    for line in path.read_text().splitlines():
        event = json.loads(line)
        event_type = event.get("type", "")
        if not any(fnmatch.fnmatch(event_type, p) for p in topics):
            continue
        envelope = EventPushEnvelope(event=event)
        writer.write(envelope.model_dump_json().encode() + b"\n")
        count += 1

    if count:
        await writer.drain()
    return count
```

历史事件和实时事件用同样的 `EventPushEnvelope` 格式发出，客户端不需要区分——先收到一批历史，然后无缝接到实时流上。`EventSubscribeResult.replayed_count` 告诉客户端回放了多少条。

## 带 replay_from_run 重连时的顺序

```
SocketClient                              CoreApp
    │                                         │
    │ event.subscribe                         │
    │ replay_from_run=run_id ────────────────→│ _replay_events(run_id)
    │                                         │         ↓
    │                              events.jsonl 读取历史事件行
    │                                         │         ↓
    │←────────────────────────────────────────│ 历史 EventPushEnvelope × N
    │                                         │ 与实时事件格式相同
    │                                         │         ↓
    │                                         │ broadcaster.subscribe(writer, topics)
    │←────────────────────────────────────────│ 注册实时订阅
    │                                         │         ↓
    │←════════════════════════════════════════│ 新事件实时推送
    │              实时（紫色）                 │
    │                                         │
    ↓                                         ↓
 on_event(handler)                       IpcEventBroadcaster
```

历史先于实时；两者格式相同（EventPushEnvelope），客户端无需区分。

`kama-tui` 支持 `--replay` 参数来触发这个流程：

```
uv run kama-tui --replay 20260515-abc
```
