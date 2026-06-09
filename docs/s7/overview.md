# S7-Skills、Subagents 与 MCP

## 第 7 阶段：Skills、Subagents 与 MCP

| 项目 | 内容 |
|------|------|
| 阶段 | s7 |
| 分支 | `stage/s7` |
| 本阶段新增 | Skills 斜杠命令、子 Agent、角色配置、后台 agent_result、MCP 外部工具接入 |
| 依赖上一阶段 | s6 的 SessionManager、AgentRunner、TUI、权限系统和上下文治理 |

## 本阶段要做什么

s6 之后，单个 agent 已经能长期会话，能安全调用工具，能压缩上下文，还能看到项目级 context。

但它仍然是**一个 agent 在一条上下文里做所有事**。

这在小任务里没问题。一旦任务变成：

```text
重构 core/runner.py：先分析影响范围，再改代码，最后做审查
```

单 agent 模型就开始别扭。分析阶段应该尽量只读；执行阶段需要写文件；审查阶段要挑问题，最好不要继续改。三个阶段的目标、语气、工具权限都不一样。把它们塞进同一个 system prompt，只能靠 LLM 自己切换角色。

另一个边界是工具。内建工具再多，也不可能覆盖所有外部系统：数据库、公司知识库、GitHub、内部 API。我们不应该为了每个外部服务都改 kama 源码。

s7 引入三件事来突破这些边界：

- **Skills**：用户用 `/review ...`、`/orchestrate ...` 触发预定义工作流。
- **Subagents**：父 agent 可以派生隔离的子 agent，把分析、执行、审查拆开跑。
- **MCP**：daemon 启动时连接外部工具服务器，把它们包装成普通 ToolRegistry 工具。

这一章顺着一次命令走：

```text
/orchestrate 对 core/runner.py 做一轮重构分析和代码审查
```

路径是：SessionManager 识别斜杠命令 → SkillLoader 渲染 prompt 和工具白名单 → AgentRunner 构造受限 registry → 父 Agent 调 `spawn_agent` → 子 Agent 按角色运行 → 事件桥回 TUI → 必要时通过 MCP 工具访问外部能力。

## s7 整体调用链

```
TUI / kama-tui
    │
    ▼
SessionManager ──斜杠命令──→ SkillLoader
    │                         (system_prompt / tool_whitelist)
    ▼
AgentRunner ←──────────────────────────────┐
    │                                       │
    ▼                                       │
父 AgentLoop (spawn_agent / task)           │
    │                                       │
    ├──→ planner (子 agent)                 │
    ├──→ executor (子 agent)                │
    └──→ reviewer (子 agent)                │
         │                                  │
         └── 事件桥 ──→ parent_bus ──→ IpcEventBroadcaster ──→ TUI
    │
    ▼
McpServerManager ←── 注入 ToolRegistry
    │
    └──→ MCP Servers (stdio / tcp)
              │
              └──→ McpTool (server__tool)
```
