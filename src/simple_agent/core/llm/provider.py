from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

from simple_agent.core.events.bus import EventBus
from simple_agent.core.events.types import LlmRequestEvent, LlmTokenEvent, LlmUsageEvent


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LlmUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    context_pct: float = 0.0


@dataclass
class LlmResponse:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = ""
    usage: LlmUsage | None = None


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
                    stream_options={"include_usage": True},
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
        raw_usage: Any | None = None

        async for chunk in response:
            if getattr(chunk, "usage", None) is not None:
                raw_usage = chunk.usage
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

        usage = _parse_usage(raw_usage, self._model)
        if usage is not None:
            await bus.publish(
                LlmUsageEvent(
                    run_id=run_id,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_read_input_tokens=usage.cache_read_input_tokens,
                    cache_creation_input_tokens=usage.cache_creation_input_tokens,
                    context_pct=usage.context_pct,
                    ts=_now(),
                )
            )

        return LlmResponse(
            text="".join(text_parts),
            tool_calls=result_tool_calls,
            stop_reason=stop_reason,
            usage=usage,
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


def _parse_usage(raw_usage: Any | None, model: str) -> LlmUsage | None:
    if raw_usage is None:
        return None

    input_tokens = _usage_int(raw_usage, "input_tokens", "prompt_tokens")
    output_tokens = _usage_int(raw_usage, "output_tokens", "completion_tokens")
    cache_read = _usage_int(raw_usage, "cache_read_input_tokens")
    cache_create = _usage_int(raw_usage, "cache_creation_input_tokens")

    prompt_details = _usage_value(raw_usage, "prompt_tokens_details")
    if cache_read == 0 and prompt_details is not None:
        cache_read = _usage_int(prompt_details, "cached_tokens")

    window = _context_window(model)
    context_pct = input_tokens / window if window > 0 else 0.0
    return LlmUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_create,
        context_pct=context_pct,
    )


def _usage_int(obj: Any, *names: str) -> int:
    for name in names:
        value = _usage_value(obj, name)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def _usage_value(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _context_window(model: str) -> int:
    name = model.lower()
    if "claude" in name:
        return 200_000
    if "gpt-4.1" in name or "gpt-5" in name:
        return 1_000_000
    if "qwen" in name or "glm" in name:
        return 128_000
    return 128_000
