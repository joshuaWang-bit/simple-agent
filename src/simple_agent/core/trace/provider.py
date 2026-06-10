from __future__ import annotations

import time
from typing import Any

from simple_agent.core.llm.provider import LlmResponse, OpenAICompatibleProvider
from simple_agent.core.trace.record import TraceRecord, _now
from simple_agent.core.trace.writer import TraceWriter


class TracingProvider:
    def __init__(
        self,
        inner: OpenAICompatibleProvider,
        trace: TraceWriter,
        *,
        include_payload: bool,
    ) -> None:
        self._inner = inner
        self._trace = trace
        self._include_payload = include_payload

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        bus: Any,
        run_id: str,
        *,
        step: int = 0,
        system: str | None = None,
    ) -> LlmResponse:
        # 调用前：记录 CORE→LLM
        if self._include_payload:
            call_data: dict[str, Any] = {
                "messages": messages,
                "tool_schemas": tool_schemas,
            }
        else:
            call_data = {
                "message_count": len(messages),
                "tool_count": len(tool_schemas),
            }

        self._trace.emit(
            TraceRecord(
                ts=_now(),
                direction="CORE→LLM",
                layer="llm",
                kind="api_call",
                run_id=run_id,
                step=step,
                data=call_data,
            )
        )

        t0 = time.monotonic()
        result = await self._inner.chat(
            messages, tool_schemas, bus, run_id, step=step, system=system
        )
        latency_ms = int((time.monotonic() - t0) * 1000)

        # 调用后：记录 LLM→CORE
        if self._include_payload:
            resp_data: dict[str, Any] = {
                "stop_reason": result.stop_reason,
                "latency_ms": latency_ms,
                "text": result.text,
                "tool_calls": [
                    {"id": tc.id, "name": tc.name, "input": tc.input}
                    for tc in result.tool_calls
                ],
            }
        else:
            resp_data = {
                "stop_reason": result.stop_reason,
                "latency_ms": latency_ms,
                "tool_count": len(result.tool_calls),
            }

        self._trace.emit(
            TraceRecord(
                ts=_now(),
                direction="LLM→CORE",
                layer="llm",
                kind="api_response",
                run_id=run_id,
                step=step,
                data=resp_data,
            )
        )
        return result
