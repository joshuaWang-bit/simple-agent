# AgentRunner 把所有零件组装起来

`AgentRunner.run()` 是真正的组装现场。在 `AgentLoop` 开始循环之前，它需要把所有依赖都准备好：

```python
# core/runner.py（节选）

async def run(self, goal: str) -> None:
    # 1. 为这次运行生成唯一 ID，创建对应目录
    run_id = new_run_id()
    run_path = self._runs_dir / run_id
    run_path.mkdir(parents=True, exist_ok=True)

    # 2. 建立事件总线，订阅所有监听者
    bus = EventBus()
    for h in self._extra_handlers:
        bus.subscribe(h)

    # 3. 根据 tier 选择模型，准备 LLM、工具注册表、循环控制器
    model = self._resolve_model()   # fast / pro / ultra
    provider = self._provider or OpenAICompatibleProvider(
        model=model,
        api_base=self._config.llm_api_base,
        api_key=self._config.llm_api_key,
    )
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    loop = AgentLoop(provider, registry, bus)

    # 4. 创建"工作记忆"，goal 在这里成为第一条消息
    context = ExecutionContext(
        run_id=run_id, goal=goal, max_steps=self._config.agent_max_steps
    )

    # 5. 打开事件文件，然后正式开始
    async with EventWriter(run_path / "events.jsonl") as writer:
        writer.subscribe(bus)
        await bus.publish(RunStartedEvent(run_id=run_id, goal=goal, ts=_now()))
        ...
        await loop.run(context)
        ...
        await bus.publish(RunFinishedEvent(...))
```

`run_id` 的格式是 `YYYYMMDD-HHMMSS-xxxxxx`（例如 `20260511-161020-abc123`），时间戳让 `ls runs/` 后能一眼认出最近一次运行，6 位随机十六进制保证同一秒内多次启动不会冲突。

注意 `EventWriter` 是用 `async with` 打开的。这保证无论后面发生什么——正常完成、报错、被 Ctrl+C 中断——事件文件都会被正确关闭，不会留下损坏的文件。
