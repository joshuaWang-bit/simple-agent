# 守护进程启动 run

用户的命令经过 CLI → SocketClient → daemon 这条 s2 已经建好的链路，到达 `CoreApp._agent_run_handler`：

```python
# core/app.py

async def _agent_run_handler(self, params: dict[str, Any]) -> AgentRunResult:
    cmd = AgentRunCommand.model_validate(params)
    run_id = new_run_id()
    runner = AgentRunner(self._config, bus=self._bus, trace=self._trace)
    run_task = asyncio.create_task(runner.run(cmd.goal, run_id=run_id))
    self._running_runs.add(run_task)
    run_task.add_done_callback(self._running_runs.discard)
    return AgentRunResult(run_id=run_id)
```

这里有一个重要的细节：`run_id` 在 handler 里生成，然后传入 `runner.run()`。这样 `AgentRunResult` 能立刻把 `run_id` 返回给客户端——TUI 在 agent 跑完之前就拿到了 `run_id`，可以提前准备订阅，不会错过 `run.started` 事件。

`asyncio.create_task()` 把整个 run 甩到后台异步执行，handler 立即返回，不阻塞 socket 服务器接收下一条命令。`_running_runs` 维护一个活跃 task 的集合，shutdown 时逐个 cancel，保证进程不会在 agent 还在跑的时候直接退出。
