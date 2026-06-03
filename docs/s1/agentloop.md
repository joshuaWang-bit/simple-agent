# AgentLoop

准备工作做完了，`AgentLoop.run()` 正式开始循环：

```python
# core/loop.py

async def run(self, context: ExecutionContext) -> None:
    while not context.is_done():
        context.step += 1
        await self._bus.publish(StepStartedEvent(...))

        # — plan: 让 LLM 思考下一步 —
        try:
            response = await self._provider.chat(
                messages=context.messages,
                tool_schemas=self._registry.tool_schemas(),
                bus=self._bus,
                run_id=context.run_id,
            )
        except asyncio.CancelledError:
            context.mark_failed("cancelled")
            raise   # 必须向上传播，见下方说明
        except Exception:
            context.mark_failed("llm_error")
            break

        # — observe: 把 LLM 响应追加到对话历史 —
        tool_calls = None
        if response.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.input),
                    },
                }
                for tc in response.tool_calls
            ]
        context.add_assistant_message(response.text or "", tool_calls)

        # — act: 如果 LLM 要求调用工具，执行它 —
        if response.stop_reason == "tool_use":
            for tc in response.tool_calls:
                result = await invoke_tool(self._registry, tc, self._bus, context.run_id)
                context.add_tool_result(tc.id, result.content)

        # — 终止检查 —
        if response.stop_reason == "end_turn":
            context.mark_success()
        elif context.step >= context.max_steps:
            context.mark_failed("exceeded_max_steps")

        await self._bus.publish(StepFinishedEvent(...))
```

## 为什么顺序是 observe → act，而不是 act → observe？

OpenAI 兼容 API 的消息格式有严格要求：`assistant` 的回复（包括 `tool_calls`）必须先出现在历史里，`tool` 结果作为下一条消息紧随其后。如果先执行工具（act）再记录 LLM 响应（observe），消息顺序就乱了，下一次调用 API 会报错。

## 工具调用失败了，循环停不停？

不停。`invoke_tool()` 的契约是永不抛出异常——无论工具执行成功还是失败，都返回一个 `ToolResult`，`is_error` 字段说明是否出错。失败的结果同样通过 `add_tool_result()` 追加进对话历史，让 LLM 看到"这个工具出错了"，然后自己决定怎么办（换路径、报告给用户、还是放弃）。这是 agent 和普通脚本最本质的区别：agent 能从错误中恢复。

## CancelledError 为什么必须 re-raise？

当用户按 Ctrl+C，asyncio 会向正在运行的协程发送 `CancelledError`。如果我们在 `except` 里吞掉它而不 `raise`，asyncio 不知道取消发生了，程序就无法正常退出。我们捕获它唯一的目的是在 re-raise 之前有机会更新 `context.status`，让 `RunFinishedEvent` 能记录正确的终止原因。

## 循环的终止条件汇总

| 触发条件 | 结果 |
|----------|------|
| LLM 返回 `end_turn` | `success` |
| 步数达到 `max_steps`（默认 20） | `failed: exceeded_max_steps` |
| LLM API 报错 | `failed: llm_error` |
| Ctrl+C | `failed: cancelled` |
| 工具执行出错 | **不终止**，错误作为结果送回 LLM |
