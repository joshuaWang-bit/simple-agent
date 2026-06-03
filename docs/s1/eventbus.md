# EventBus——让所有人都能听到

在循环开始前，先弄清楚 `EventBus` 是什么，因为后面所有代码都会用到它。

```python
# core/events/bus.py

class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[EventHandler] = []

    def subscribe(self, handler: EventHandler) -> None:
        self._subscribers.append(handler)

    async def publish(self, event: BaseModel) -> None:
        for handler in self._subscribers:
            await handler(event)
```

`EventBus` 是一个广播中心。任何代码调用 `bus.publish(某个事件)`，所有订阅了这个 bus 的处理函数就会按注册顺序依次收到它。

s1 里有三个订阅者：

- `EventWriter.handle`：把事件序列化成 JSON 行，写入 `events.jsonl`
- `StdoutPrinter.handle`：把事件格式化后打印到终端
- `AgentRunner` 传进来的 `extra_handlers`（目前就是 `StdoutPrinter`，这两条是同一个东西）

## EventBus：一个事件，多个接收者

## 为什么要这样设计？

为什么用 EventBus，而不是在每个需要打印或记录的地方直接调用？

因为 `AgentLoop` 不应该知道外面有没有终端，有没有文件要写。它只需要"广播一件事发生了"，至于谁关心、怎么处理，是外面的事。这样 `AgentLoop` 的代码保持干净，测试时也可以接一个简单的 mock handler 而不需要真实的文件系统。

## EventWriter：每写一行就立即 flush

```python
# core/events/writer.py（节选）

async def handle(self, event: BaseModel) -> None:
    try:
        self._file.write(event.model_dump_json() + "\n")
        self._file.flush()   # 立即刷盘，不等缓冲区满
    except (OSError, ValueError) as e:
        logger.error("EventWriter: failed to write event: %s", e)
```

每写一行就立即调用 `flush()`，不做批量缓冲。代价是频繁的磁盘写入，但好处是：如果程序在任何一步崩溃了，已记录的事件不会丢失。`OSError` 在这里不会重新抛出——磁盘满了不应该导致 agent 停止工作。

## 事件类型是什么样的

所有事件都是 pydantic 模型，定义在 `core/bus/events.py` 里：

```python
class RunStartedEvent(BaseModel):
    type: Literal["run.started"] = "run.started"
    run_id: str
    goal: str
    ts: str   # ISO 8601 时间戳，例如 "2026-05-11T16:10:20.001Z"

class LlmTokenEvent(BaseModel):
    type: Literal["llm.token"] = "llm.token"
    run_id: str
    token: str   # LLM 流式输出的单个文本片段
    ts: str

class ToolCallFinishedEvent(BaseModel):
    type: Literal["tool.call_finished"] = "tool.call_finished"
    run_id: str
    tool_use_id: str
    tool_name: str
    elapsed_ms: int
    ts: str
```

每种事件的 `type` 字段是固定的字符串常量（`Literal`），写进 `events.jsonl` 后，读取时可以用 `type` 字段来判断这行是什么类型的事件。s1 共有 11 种事件类型，覆盖 run、step、LLM 调用、工具调用的全部生命周期。
