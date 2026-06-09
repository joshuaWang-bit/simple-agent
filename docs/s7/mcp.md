# MCP：把外部工具接进 ToolRegistry

Skills 和 subagents 解决的是"怎么组织 agent 工作"。MCP 解决的是"工具从哪里来"。

daemon 启动时，`CoreApp` 创建 `McpServerManager`，根据配置连接外部 server：

```python
self._mcp_manager = McpServerManager()
if self._config.mcp.servers:
    await self._mcp_manager.start_all(self._config.mcp.servers)
```

`start_all()` 逐个连接 server，发现工具，再包装成 `McpTool`：

```python
client = await self._connect(cfg)
tool_defs = await client.list_tools()
for tool_def in tool_defs:
    self._tools.append(McpTool(client, cfg.name, tool_def))
self._clients[cfg.name] = client
```

stdio server 会作为子进程启动，tcp server 会连接已有进程：

```toml
[[mcp.servers]]
name = "filesystem"
transport = "stdio"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]

[[mcp.servers]]
name = "internal-kb"
transport = "tcp"
host = "10.0.0.5"
port = 3000
```

## McpTool 让外部工具看起来像内建工具

```python
class McpTool(BaseTool):
    def __init__(self, client, server_name, tool_def):
        self.name = f"{server_name}__{tool_def.name}"
        self.description = tool_def.description or f"MCP tool from {server_name}"
        self.input_schema = tool_def.input_schema or {"type": "object", "properties": {}}

    async def invoke(self, params):
        try:
            content = await self._client.call_tool(self._tool_def.name, dict(params))
            return ToolResult(content=content)
        except McpServerUnavailableError:
            return ToolResult(
                content=f"mcp server '{self._server_name}' unavailable",
                is_error=True,
                error_type="runtime_error",
            )
```

工具名带 server 前缀，比如 `filesystem__read_file`。这样不会和内建 `read_file` 冲突，也能让 LLM 看出工具来自哪个 server。

## 注入 ToolRegistry

每次 run 构造 registry 时，runner 注入已发现的 MCP 工具：

```python
if self._mcp_manager is not None:
    for mcp_tool in self._mcp_manager.get_tools():
        if _ok(mcp_tool.name):
            registry.register(mcp_tool)
```

MCP 工具走同一条 `invoke_tool()` 路径，所以 s5 的权限、失败分类、TUI 展示都能复用。server 不可用时，`McpTool` 返回 `is_error=True`，AgentLoop 不需要特殊分支。

## MCP 接入结构

```
CoreApp
    │
    ▼ 启动
McpServerManager
    │
    ├── 连接 ──→ MCP server A (stdio 子进程)
    │                  │
    │                  ├── list_tools ──→ McpTool A__tool1
    │                  └── list_tools ──→ McpTool A__tool2
    │
    └── 连接 ──→ MCP server B (tcp 远程服务)
                       │
                       └── list_tools ──→ McpTool B__tool1
                                         │
                                         └── 注入 ──→ ToolRegistry
                                                       │
                                                       └── invoke_tool ──→ McpTool.invoke ──→ Client.call_tool
                                                                                                  │
                                                                                                  └── stdio/tcp ──→ 外部 MCP Server
```

`McpTool` 工具名格式：`server__tool`；AgentRunner 每次 run 重新构造 ToolRegistry，将 McpTool 与内建工具一起注入。
