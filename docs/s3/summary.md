# 小结与展望

这个阶段没有改变系统的任何行为，只是在四个位置加了观察窗口。现在你能看到的东西，和 s2 结束时完全不同：

| 层面 | s2 能看到 | s3 新增 |
|------|----------|---------|
| IPC | 无 | CLIENT→CORE 命令、CORE→CLIENT 响应和推送 |
| EventBus | events.jsonl（per-run） | daemon.jsonl 里的 CORE event（全局时间线） |
| LLM | 无 | CORE→LLM 请求、LLM→CORE 响应（含 latency 和 stop_reason） |

`daemon.jsonl` 不是替代 `events.jsonl`，而是补充：前者回答"命令怎么流转"，后者回答"这次 run 里发生了什么"。两个文件一起使用，调试时可以从 IPC 层一路追踪到 LLM API，定位问题发生的精确位置。
