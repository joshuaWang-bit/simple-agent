from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from simple_agent.core.tools.base import BaseTool, ToolResult


class McpServerUnavailableError(Exception):
    pass


@dataclass(frozen=True)
class McpServerConfig:
    name: str
    transport: str
    command: str = ""
    args: list[str] = field(default_factory=list)
    host: str = ""
    port: int = 0

    @classmethod
    def from_raw(cls, raw: Any) -> "McpServerConfig":
        if isinstance(raw, cls):
            return raw
        if hasattr(raw, "model_dump"):
            data = raw.model_dump()
        elif isinstance(raw, dict):
            data = raw
        else:
            data = {
                "name": getattr(raw, "name", ""),
                "transport": getattr(raw, "transport", ""),
                "command": getattr(raw, "command", ""),
                "args": getattr(raw, "args", []),
                "host": getattr(raw, "host", ""),
                "port": getattr(raw, "port", 0),
            }
        return cls(
            name=str(data.get("name") or ""),
            transport=str(data.get("transport") or ""),
            command=str(data.get("command") or ""),
            args=[str(arg) for arg in data.get("args") or []],
            host=str(data.get("host") or ""),
            port=int(data.get("port") or 0),
        )


@dataclass(frozen=True)
class McpToolDefinition:
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "properties": {},
    })

    @classmethod
    def from_raw(cls, raw: Any) -> "McpToolDefinition":
        if isinstance(raw, cls):
            return raw
        if hasattr(raw, "model_dump"):
            data = raw.model_dump()
        elif isinstance(raw, dict):
            data = raw
        else:
            data = {
                "name": getattr(raw, "name", ""),
                "description": getattr(raw, "description", ""),
                "input_schema": getattr(raw, "input_schema", {}),
            }
        input_schema = data.get("input_schema") or data.get("inputSchema") or {}
        if not isinstance(input_schema, dict):
            input_schema = {"type": "object", "properties": {}}
        return cls(
            name=str(data.get("name") or ""),
            description=str(data.get("description") or ""),
            input_schema=input_schema or {"type": "object", "properties": {}},
        )


class McpClient(Protocol):
    async def start(self) -> None: ...
    async def list_tools(self) -> list[McpToolDefinition]: ...
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str: ...
    async def close(self) -> None: ...


class McpTool(BaseTool):
    def __init__(
        self,
        client: McpClient,
        server_name: str,
        tool_def: McpToolDefinition,
    ) -> None:
        self._client = client
        self._server_name = server_name
        self._tool_def = tool_def

    @property
    def name(self) -> str:
        return f"{self._server_name}__{self._tool_def.name}"

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self._tool_def.description
            or f"MCP tool from {self._server_name}",
            "input_schema": self._tool_def.input_schema
            or {"type": "object", "properties": {}},
        }

    async def run(self, input: dict[str, Any]) -> ToolResult:
        try:
            content = await self._client.call_tool(self._tool_def.name, dict(input))
            return ToolResult(content=content)
        except McpServerUnavailableError as exc:
            return ToolResult(
                content=str(exc) or f"mcp server '{self._server_name}' unavailable",
                is_error=True,
                error_type="runtime_error",
            )
        except Exception as exc:
            return ToolResult(
                content=f"mcp tool '{self.name}' failed: {exc}",
                is_error=True,
                error_type="runtime_error",
            )


class McpServerManager:
    def __init__(
        self,
        client_factory: Any | None = None,
    ) -> None:
        self._client_factory = client_factory
        self._clients: dict[str, McpClient] = {}
        self._tools: list[McpTool] = []

    async def start_all(self, configs: Iterable[Any]) -> None:
        for raw in configs:
            cfg = McpServerConfig.from_raw(raw)
            if not cfg.name:
                continue
            client = await self._connect(cfg)
            await client.start()
            for raw_tool in await client.list_tools():
                tool_def = McpToolDefinition.from_raw(raw_tool)
                if tool_def.name:
                    self._tools.append(McpTool(client, cfg.name, tool_def))
            self._clients[cfg.name] = client

    def get_tools(self) -> list[McpTool]:
        return list(self._tools)

    async def stop_all(self) -> None:
        clients = list(self._clients.values())
        self._clients.clear()
        self._tools.clear()
        for client in clients:
            await client.close()

    async def _connect(self, cfg: McpServerConfig) -> McpClient:
        if self._client_factory is not None:
            client = self._client_factory(cfg)
            if asyncio.iscoroutine(client):
                client = await client
            return client
        if cfg.transport == "stdio":
            return JsonRpcStdioMcpClient(cfg)
        if cfg.transport == "tcp":
            return JsonRpcTcpMcpClient(cfg)
        raise McpServerUnavailableError(
            f"unsupported mcp transport for '{cfg.name}': {cfg.transport}"
        )


class _JsonRpcMixin:
    _reader: asyncio.StreamReader | None
    _writer: asyncio.StreamWriter | None
    _next_id: int

    async def _request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        if self._reader is None or self._writer is None:
            raise McpServerUnavailableError("mcp server is not connected")

        self._next_id += 1
        req_id = self._next_id
        message = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }
        self._writer.write((json.dumps(message) + "\n").encode())
        await self._writer.drain()

        while True:
            line = await self._reader.readline()
            if not line:
                raise McpServerUnavailableError("mcp server closed the connection")
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            if response.get("id") != req_id:
                continue
            if response.get("error"):
                error = response["error"]
                raise McpServerUnavailableError(
                    str(error.get("message") or error)
                    if isinstance(error, dict)
                    else str(error)
                )
            return response.get("result")

    async def _initialize(self) -> None:
        try:
            await self._request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "simple-agent", "version": "0.0.1"},
                },
            )
            await self._notify("notifications/initialized")
        except McpServerUnavailableError:
            raise

    async def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        if self._writer is None:
            raise McpServerUnavailableError("mcp server is not connected")
        message = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        self._writer.write((json.dumps(message) + "\n").encode())
        await self._writer.drain()

    async def list_tools(self) -> list[McpToolDefinition]:
        result = await self._request("tools/list")
        tools = result.get("tools", []) if isinstance(result, dict) else []
        return [McpToolDefinition.from_raw(tool) for tool in tools]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        result = await self._request(
            "tools/call",
            {"name": name, "arguments": arguments},
        )
        return _format_mcp_content(result)


class JsonRpcStdioMcpClient(_JsonRpcMixin):
    def __init__(self, cfg: McpServerConfig) -> None:
        self._cfg = cfg
        self._process: asyncio.subprocess.Process | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._next_id = 0

    async def start(self) -> None:
        if not self._cfg.command:
            raise McpServerUnavailableError(
                f"stdio mcp server '{self._cfg.name}' has no command"
            )
        self._process = await asyncio.create_subprocess_exec(
            self._cfg.command,
            *self._cfg.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        if self._process.stdout is None or self._process.stdin is None:
            raise McpServerUnavailableError("failed to open mcp stdio pipes")
        self._reader = self._process.stdout
        self._writer = self._process.stdin
        await self._initialize()

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            await self._writer.wait_closed()
        if self._process is not None and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except TimeoutError:
                self._process.kill()


class JsonRpcTcpMcpClient(_JsonRpcMixin):
    def __init__(self, cfg: McpServerConfig) -> None:
        self._cfg = cfg
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._next_id = 0

    async def start(self) -> None:
        if not self._cfg.host or not self._cfg.port:
            raise McpServerUnavailableError(
                f"tcp mcp server '{self._cfg.name}' requires host and port"
            )
        self._reader, self._writer = await asyncio.open_connection(
            self._cfg.host,
            self._cfg.port,
        )
        await self._initialize()

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            await self._writer.wait_closed()


def _format_mcp_content(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                else:
                    parts.append(json.dumps(block, ensure_ascii=False))
            return "\n".join(part for part in parts if part)
        if content is not None:
            return str(content)
    return json.dumps(result, ensure_ascii=False)
