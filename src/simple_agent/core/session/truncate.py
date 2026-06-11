from __future__ import annotations

from typing import Any

TOOL_RESULT_LIMIT = 8_000
TOOL_RESULT_KEEP = 4_000


def truncate_tool_results(
    messages: list[dict[str, Any]],
    *,
    limit: int = TOOL_RESULT_LIMIT,
    keep: int = TOOL_RESULT_KEEP,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return list(messages)

    keep = max(0, min(keep, limit))
    result: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")

        if role == "tool" and isinstance(content, str):
            result.append(_truncate_openai_tool_message(msg, content, limit, keep))
            continue

        if role == "user" and isinstance(content, list):
            result.append(_truncate_anthropic_tool_blocks(msg, content, limit, keep))
            continue

        result.append(msg)
    return result


def _truncate_openai_tool_message(
    msg: dict[str, Any],
    content: str,
    limit: int,
    keep: int,
) -> dict[str, Any]:
    if len(content) <= limit:
        return msg
    return {**msg, "content": _truncated_text(content, keep)}


def _truncate_anthropic_tool_blocks(
    msg: dict[str, Any],
    content: list[Any],
    limit: int,
    keep: int,
) -> dict[str, Any]:
    changed = False
    new_blocks: list[Any] = []
    for block in content:
        if (
            isinstance(block, dict)
            and block.get("type") == "tool_result"
            and isinstance(block.get("content"), str)
            and len(block["content"]) > limit
        ):
            block = {**block, "content": _truncated_text(block["content"], keep)}
            changed = True
        new_blocks.append(block)
    if not changed:
        return msg
    return {**msg, "content": new_blocks}


def _truncated_text(text: str, keep: int) -> str:
    omitted = len(text) - keep
    return text[:keep] + f"\n[... {omitted} chars omitted. Full output in run events.]"
