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
        timeout: float = 120.0,
        enable_thinking: bool = False,
    ) -> None:
        import httpx

        self._model = model
        self._api_key = api_key or os.environ.get("WIKI_LLM_SILICONFLOW_API_KEY") or os.environ.get("SILICONFLOW_API_KEY", "")
        self._enable_thinking = enable_thinking
        self._client = AsyncOpenAI(
            base_url=api_base,
            api_key=self._api_key,
            timeout=httpx.Timeout(timeout, connect=10.0),
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        bus: EventBus,
        run_id: str,
        *,
        step: int = 0,
        system: str | None = None,
    ) -> LlmResponse:
        await bus.publish(
            LlmRequestEvent(run_id=run_id, model=self._model, ts=_now())
        )

        tools = _to_openai_tools(tool_schemas) if tool_schemas else []

        api_messages = list(messages)
        if system:
            api_messages.insert(0, {"role": "system", "content": system})

        extra_body: dict[str, Any] = {}
        if not self._enable_thinking:
            extra_body["enable_thinking"] = False

        retries = 0
        backoff_seconds = [20, 40, 60]

        while True:
            try:
                response = await self._client.chat.completions.create(
                    model=self._model,
                    messages=api_messages,
                    tools=tools or [],
                    max_tokens=4096,
                    stream=True,
                    extra_body=extra_body or None,
                )
                break
            except Exception as exc:
                if not self._is_retryable(exc) or retries >= len(backoff_seconds):
                    raise
                wait = backoff_seconds[retries]
                retries += 1
                import logging

                logger = logging.getLogger(__name__)
                logger.warning(
                    "LLM request failed (%s), retrying in %ds (%d/%d)...",
                    exc,
                    wait,
                    retries,
                    len(backoff_seconds),
                )
                await asyncio.sleep(wait)

        text_parts: list[str] = []
        tool_calls: dict[int, dict[str, str]] = {}
        finish_reason = ""

        async for chunk in response:
            if not chunk.choices:
                continue
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

    def _is_retryable(self, exc: Exception) -> bool:
        """Determine if an exception is worth retrying."""
        # openai-specific errors
        if hasattr(exc, "status_code"):
            code = getattr(exc, "status_code", 0)
            if code in (429, 502, 503, 504):
                return True
        # Rate limit or connection errors by name
        name = type(exc).__name__
        if name in ("RateLimitError", "APIConnectionError", "APITimeoutError"):
            return True
        return False


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
