# LLM Provider

`AgentLoop` 自己不关心 LLM 是哪个厂商的，它只依赖一个接口：`Provider.chat()`。s1 里使用 `OpenAICompatibleProvider`，对接**硅基流动 (SiliconFlow)** 的 OpenAI 兼容 API。

## 三档模型

通过配置 `llm_tier` 选择不同档次的模型：

| 档次 | 配置项 | 默认模型 |
|------|--------|----------|
| `fast` | `llm_model_fast` | `Qwen/Qwen3.6-35B-A3B` |
| `pro` | `llm_model_pro` | 待定（空则 fallback 到 fast） |
| `ultra` | `llm_model_ultra` | `THUDM/glm-5.1` |

```python
# core/config.py（节选）

llm_tier: str = "fast"
llm_api_base: str = "https://api.siliconflow.cn/v1"
llm_api_key: str | None = None
llm_model_ultra: str = "THUDM/glm-5.1"
llm_model_pro: str = ""
llm_model_fast: str = "Qwen/Qwen3.6-35B-A3B"
```

## 调用 LLM

```python
# core/llm/provider.py（节选）

async def chat(
    self,
    messages: list[dict],
    tool_schemas: list[dict],
    bus: EventBus,
    run_id: str,
) -> LlmResponse:
    await bus.publish(LlmRequestEvent(...))

    tools = _to_openai_tools(tool_schemas)
    response = await self._client.chat.completions.create(
        model=self._model,
        messages=messages,
        tools=tools,
        max_tokens=4096,
        stream=True,
    )

    text_parts = []
    tool_calls: dict[int, dict] = {}
    async for chunk in response:
        delta = chunk.choices[0].delta
        if delta.content:
            text_parts.append(delta.content)
            await bus.publish(LlmTokenEvent(...))
        if delta.tool_calls:
            for tc in delta.tool_calls:
                tool_calls[tc.index] = ...  # 累积 id / name / arguments

    return LlmResponse(
        text="".join(text_parts),
        tool_calls=...,
        stop_reason=...,   # "end_turn" | "tool_use" | ...
    )
```

## 工具 schema 转换

硅基流动兼容 OpenAI 的 function calling 格式，和 Anthropic 的格式不同。`ToolRegistry` 内部仍用 Anthropic 风格的 schema（`name` + `description` + `input_schema`），Provider 在调用前自动转换：

```python
def _to_openai_tools(schemas: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s.get("description", ""),
                "parameters": s.get("input_schema", {"type": "object"}),
            },
        }
        for s in schemas
    ]
```

## 流式输出

`stream=True` 开启后，LLM 的回复是逐段到达的。`LlmTokenEvent` 每收到一段文本就广播一次，这样终端可以实时打字效果，而不是等全部内容收完才显示。

工具参数（`arguments`）也是流式的，需要按 `index` 累积到一个字典里，最后 `json.loads()` 转成字典。
