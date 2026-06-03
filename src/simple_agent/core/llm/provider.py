from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

from simple_agent.core.events.bus import EventBus
from simple_agent.core.events.types import LlmRequestEvent, LlmTokenEvent


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LlmResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = ""


class OpenAICompatibleProvider:
    """OpenAI-compatible LLM provider (SiliconFlow, etc.)."""

    def __init__(
        self,
        model: str,
        api_base: str = "https://api.siliconflow.cn/v1",
        api_key: str | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key or os.environ.get("WIKI_LLM_SILICONFLOW_API_KEY") or os.environ.get("SILICONFLOW_API_KEY", "")
        self._client = AsyncOpenAI(
            base_url=api_base,
            api_key=self._api_key,
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        bus: EventBus,
        run_id: str,
    ) -> LlmResponse:
        await bus.publish(
            LlmRequestEvent(run_id=run_id, model=self._model, ts=_now())
        )

        tools = _to_openai_tools(tool_schemas) if tool_schemas else []

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools or [],
            max_tokens=4096,
            stream=True,
        )

        text_parts: list[str] = []
        tool_calls: dict[int, dict[str, str]] = {}
        finish_reason = ""

        async for chunk in response:
            choice = chunk.choices[0]
            delta = choice.delta

            if choice.finish_reason:
                finish_reason = choice.finish_reason

            if delta.content:
                text_parts.append(delta.content)
                await bus.publish(
                    LlmTokenEvent(
                        run_id=run_id,
                        token=delta.content,
                        ts=_now(),
                    )
                )

            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_calls:
                        tool_calls[idx] = {"id": "", "name": "", "arguments": ""}
                    if tc_delta.id:
                        tool_calls[idx]["id"] = tc_delta.id
                    if tc_delta.function and tc_delta.function.name:
                        tool_calls[idx]["name"] = tc_delta.function.name
                    if tc_delta.function and tc_delta.function.arguments:
                        tool_calls[idx]["arguments"] += tc_delta.function.arguments

        result_tool_calls: list[ToolCall] = []
        for tc in tool_calls.values():
            try:
                args = json.loads(tc["arguments"])
            except json.JSONDecodeError:
                args = {}
            result_tool_calls.append(
                ToolCall(id=tc["id"], name=tc["name"], input=args)
            )

        stop_reason = ""
        if finish_reason == "stop":
            stop_reason = "end_turn"
        elif finish_reason == "tool_calls":
            stop_reason = "tool_use"
        elif finish_reason:
            stop_reason = finish_reason

        return LlmResponse(
            text="".join(text_parts),
            tool_calls=result_tool_calls,
            stop_reason=stop_reason,
        )


def _to_openai_tools(schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Anthropic-style tool schemas to OpenAI function format."""
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
