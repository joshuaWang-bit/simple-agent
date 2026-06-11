from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from simple_agent.core.tools.base import BaseTool, ToolResult


class BashParams(BaseModel):
    model_config = ConfigDict(extra="ignore")
    command: str
    timeout: float = Field(default=60.0, gt=0, le=120.0)


class BashTool(BaseTool):
    params_model = BashParams

    @property
    def name(self) -> str:
        return "bash"

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": "Execute a shell command. stdout and stderr are merged. Output is truncated to 64 KB.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default 60, max 120)",
                    },
                },
                "required": ["command"],
            },
        }

    async def run(self, input: dict[str, Any]) -> ToolResult:
        p = BashParams.model_validate(input)
        proc = await asyncio.create_subprocess_shell(
            p.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout_bytes, _ = await asyncio.wait_for(
                proc.communicate(), timeout=p.timeout
            )
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            return ToolResult(
                content=f"[timeout after {p.timeout}s]",
                is_error=True,
                error_type="timeout",
            )

        output = stdout_bytes.decode("utf-8", errors="replace")
        # Truncate to 64 KB
        if len(output) > 65536:
            output = output[:65536] + "\n[output truncated]"

        if proc.returncode != 0:
            return ToolResult(
                content=f"[exit {proc.returncode}]\n{output}",
                is_error=True,
            )
        return ToolResult(content=output or "[no output]")
