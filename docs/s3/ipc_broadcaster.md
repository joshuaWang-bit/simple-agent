# 埋点 ②：IPC 层——IpcEventBroadcaster

broadcaster 每次成功推送事件之后，写一条 `push` 记录：

```python
# core/transport/ipc_broadcaster.py（节选）

sub.writer.write(envelope.model_dump_json().encode() + b"\n")
await sub.writer.drain()
if self._trace is not None:
    self._trace.emit(
        TraceRecord(
            direction="CORE→CLIENT",
            layer="ipc",
            kind="push",
            run_id=run_id,
            client_id=client_id,
            data={"sub_id": sub.sub_id, "event_type": event_type},
        )
    )
```

`push` 记录里**不包含完整的 event body**，只记录 `sub_id` 和 `event_type`。原因：完整 event 已经在 `CORE` event 记录里了（埋点 ③）；如果 `push` 也完整记录，同一个 event 有几个订阅者就会在 trace 文件里出现几遍，文件体积翻几倍，查阅时也多余。`push` 记录的意义是"谁（sub_id/client_id）收到了这个事件类型"，摘要已经足够。
