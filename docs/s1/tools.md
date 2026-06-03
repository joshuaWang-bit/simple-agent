# 工具系统

## ToolRegistry：工具注册表

```python
# core/tools/registry.py

class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def tool_schemas(self) -> list[dict]:
        return [t.schema for t in self._tools.values()]

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)
```

注册表只做三件事：注册工具、提取 schema 列表、按名字查找。没有花哨的功能，够用就行。

## BaseTool 接口

```python
# core/tools/base.py

class BaseTool(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def schema(self) -> dict: ...

    @abstractmethod
    async def run(self, input: dict) -> ToolResult: ...
```

`ToolResult` 是一个简单的数据类：

```python
@dataclass
class ToolResult:
    content: str
    is_error: bool = False
```

## ReadFileTool

s1 里唯一内置的工具：

```python
# core/tools/read_file.py

class ReadFileTool(BaseTool):
    name = "read_file"

    @property
    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": "Read the contents of a file.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"}
                },
                "required": ["path"]
            }
        }

    async def run(self, input: dict) -> ToolResult:
        path = Path(input["path"])
        try:
            return ToolResult(content=path.read_text(encoding="utf-8"))
        except Exception as e:
            return ToolResult(content=str(e), is_error=True)
```

注意 `run()` 永远不会抛异常，失败时把错误信息作为 `content` 返回，`is_error=True`。这样 LLM 能看到"文件不存在"或"权限不足"，决定下一步怎么办。

## invoke_tool：执行一次工具调用

```python
# core/tools/invoke.py

async def invoke_tool(
    registry: ToolRegistry,
    tc: ToolCall,
    bus: EventBus,
    run_id: str,
) -> ToolResult:
    tool = registry.get(tc.name)
    if not tool:
        return ToolResult(content=f"Unknown tool: {tc.name}", is_error=True)

    await bus.publish(ToolCallStartedEvent(...))
    t0 = time.perf_counter()
    try:
        result = await tool.run(tc.input)
    except Exception as e:
        result = ToolResult(content=str(e), is_error=True)
    elapsed = int((time.perf_counter() - t0) * 1000)

    await bus.publish(ToolCallFinishedEvent(...))
    return result
```

`invoke_tool` 做了三件事：
1. 查找工具
2. 执行并计时
3. 广播开始/结束事件

如果工具不存在，或者执行时抛出异常，都会被捕获并包装成 `is_error=True` 的结果，不会中断循环。
