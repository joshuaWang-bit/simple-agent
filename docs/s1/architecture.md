# 代码结构图（文字版）

## 一次 `sagent run` 的执行链路

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  用户                                                                       │
│  $ sagent run --goal "总结 README.md 的主要章节"                            │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  CLI 入口 (cli/main.py)                                                     │
│  argparse 解析 --goal → cmd_run(goal, config)                               │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  cmd_run (cli/commands/run.py)                                              │
│  printer = StdoutPrinter()                                                  │
│  runner = AgentRunner(config, extra_handlers=[printer.handle])              │
│  asyncio.run(runner.run(goal))                                              │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  AgentRunner.run() (core/runner.py)                                         │
│  1. run_id = new_run_id()                                                   │
│  2. run_path = runs_dir / run_id → mkdir                                    │
│  3. bus = EventBus()                                                        │
│  4. bus.subscribe(printer.handle)                                           │
│  5. provider = AnthropicProvider(config.llm.default_model)                  │
│  6. registry = ToolRegistry(); registry.register(ReadFileTool())            │
│  7. loop = AgentLoop(provider, registry, bus)                               │
│  8. context = ExecutionContext(run_id, goal, max_steps)                     │
│  9. async with EventWriter(run_path / "events.jsonl") as writer:            │
│       writer.subscribe(bus)                                                 │
│       bus.publish(RunStartedEvent(...))                                     │
│       loop.run(context)                                                     │
│       bus.publish(RunFinishedEvent(...))                                    │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  AgentLoop.run() (core/loop.py)                                             │
│  while not context.is_done():                                               │
│      context.step += 1                                                      │
│      bus.publish(StepStartedEvent(...))                                     │
│                                                                             │
│      # plan                                                                 │
│      response = await provider.chat(messages, tool_schemas, bus, run_id)    │
│                                                                             │
│      # observe                                                              │
│      context.add_assistant_message(blocks)                                  │
│                                                                             │
│      # act                                                                  │
│      if response.stop_reason == "tool_use":                                 │
│          for tc in response.tool_calls:                                     │
│              result = await invoke_tool(registry, tc, bus, run_id)          │
│              context.add_tool_result(tc.id, result.content,                 │
│                                       is_error=result.is_error)             │
│                                                                             │
│      # 终止检查                                                             │
│      if response.stop_reason == "end_turn":                                 │
│          context.mark_success()                                             │
│      elif context.step >= context.max_steps:                                │
│          context.mark_failed("exceeded_max_steps")                          │
│                                                                             │
│      bus.publish(StepFinishedEvent(...))                                    │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │
              ┌─────────────────┴─────────────────┐
              │                                   │
              ▼                                   ▼
┌─────────────────────────┐           ┌─────────────────────────┐
│  provider.chat()        │           │  invoke_tool()          │
│  (core/llm/provider.py) │           │  (core/tools/invoke.py) │
│                         │           │                         │
│  SiliconFlow / OpenAI   │           │  registry.get(tc.name)  │
│  stream=True            │           │  tool.run(tc.input)     │
│  广播 LlmTokenEvent     │           │  广播 ToolCallStarted   │
│                         │           │  广播 ToolCallFinished  │
└─────────────────────────┘           └─────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────┐
│  事件通道（与主调用链并行）                                                  │
│                                                                             │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐              │
│  │ 所有模块 │───→│ EventBus │───→│ EventWri │───→│ events.  │              │
│  │ 发布事件 │    │ 广播中心 │    │ ter      │    │ jsonl    │              │
│  └──────────┘    └────┬─────┘    └──────────┘    └──────────┘              │
│                       │                                                     │
│                       └────────────────→ StdoutPrinter → 终端               │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 关键数据流

1. **用户输入** → `goal` 字符串
2. **AgentRunner** 组装所有组件，创建 `ExecutionContext`
3. **AgentLoop** 驱动 plan → observe → act 循环
4. **provider.chat()** 与 LLM 交互，流式接收 token
5. **invoke_tool()** 执行工具，结果回写 `context.messages`
6. **EventBus** 广播所有事件 → `EventWriter`（持久化）+ `StdoutPrinter`（终端）
7. **循环终止** → `RunFinishedEvent` → 文件关闭
