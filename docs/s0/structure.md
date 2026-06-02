# S0 项目结构

## 为什么选择 src layout

在写任何业务代码之前，项目首先要能被正确**安装和导入**。s0 使用 **src layout**：业务代码都放在 `src/simple_agent/` 下面，根目录只保留项目配置、文档和脚本。

```
simple-agent/
├── src/simple_agent/
│   ├── __init__.py
│   ├── cli/                          # 前台 CLI
│   │   ├── __init__.py
│   │   ├── main.py                   # argparse 入口、命令分发
│   │   └── commands/
│   │       ├── __init__.py
│   │       ├── ping.py               # `sagent ping` 实现
│   │       └── version.py            # `sagent --version` 实现
│   ├── core/                         # 后台 Core（daemon）
│   │   ├── __init__.py
│   │   ├── app.py                    # CoreApp：启动服务器、注册 handler、信号处理
│   │   ├── config.py                 # AgentConfig 与配置加载逻辑
│   │   ├── bus/                      # 协议模型（bus = message bus）
│   │   │   ├── __init__.py
│   │   │   ├── commands.py           # PingCommand, PongResult, Command 联合类型
│   │   │   ├── envelope.py           # JsonRpcRequest, JsonRpcSuccess, JsonRpcError
│   │   │   └── events.py             # PlaceholderEvent（s0 占位）
│   │   └── transport/
│   │       ├── __init__.py
│   │       └── socket_server.py      # asyncio TCP 服务器（NDJSON 读写）
│   └── tui/                          # 预留：后续 TUI 界面
│       └── __init__.py
├── docs/
│   └── s0/                           # S0 阶段文档（你正在看的）
├── scripts/
│   └── gen_protocol_doc.py           # 自动生成 WIRE_PROTOCOL.md
├── WIRE_PROTOCOL.md                  # 自动生成的协议文档
├── pyproject.toml
├── uv.lock
└── Makefile
```

### pyproject.toml 配置

```toml
[project]
name = "SimpleAgent"
version = "0.0.1"
requires-python = ">=3.12,<3.14"
dependencies = [
    "pydantic>=2.0",
    "python-dotenv>=1.0",
]

[project.scripts]
sagent     = "simple_agent.cli.main:main"
sagent-core = "simple_agent.core.app:run"
```

这里的重点不是"目录看起来整齐"，而是 **import 方式稳定**。`uv sync` 会把 `simple_agent` 以 **editable 模式** 装进虚拟环境，之后无论从仓库根目录、测试目录还是脚本里启动，`from simple_agent.core.config import get_config` 都能走同一套导入路径。

如果直接把源码堆在仓库根目录，很多 import 只有在"当前工作目录刚好是项目根"时才成立。到了测试、脚本生成文档、CLI 入口混在一起的时候，这种隐式假设会变成很难定位的问题。

## 关键入口

| 命令 | 模块路径 | 说明 |
|------|----------|------|
| `sagent` | `simple_agent.cli.main:main` | CLI 入口，支持 `ping`, `--version` |
| `sagent-core` | `simple_agent.core.app:run` | Daemon 入口，启动 TCP 服务器 |

## 模块职责

### `cli/`
- 只负责**解析用户输入**和**展示结果**
- 不直接处理业务逻辑，而是把请求通过网络发给 `core`
- s0 阶段只有一个 `ping` 子命令

### `core/`
- **app.py**：生命周期管理（启动、停止、信号处理）
- **config.py**：配置模型和加载（TOML + env + 默认值的优先级）
- **bus/**：
  - `commands.py` —— 强类型的请求/响应模型（Pydantic BaseModel）
  - `envelope.py` —— JSON-RPC 2.0 信封格式（与具体业务无关的通用协议层）
  - `events.py` —— 事件模型（s0 阶段只有占位）
- **transport/**：
  - `socket_server.py` —— 纯传输层，负责 TCP 连接的建立/关闭、按行读写、JSON-RPC 路由和错误封装

### 分层原则

```
cli/commands/ping.py          # 用户界面层
        │
        │  发起 JsonRpcRequest（通过 asyncio.open_connection）
        ▼
core/transport/socket_server.py  # 传输层：TCP + NDJSON + JSON-RPC 路由
        │
        │  调用 registered handler
        ▼
core/app.py                    # 应用层：CoreApp._ping_handler
        │
        │  操作业务模型
        ▼
core/bus/commands.py           # 协议模型：PingCommand / PongResult
```

s0 阶段虽然代码量不大，但已经建立了清晰的分层边界，后续阶段扩展命令、事件、LLM 调用时都可以沿用这套结构。
