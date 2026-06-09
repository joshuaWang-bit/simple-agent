# S6-让上下文可控、可压缩、可续航

## 第 6 阶段：让上下文可控、可压缩、可续航

| 项目 | 内容 |
|------|------|
| 阶段 | s6 |
| 分支 | `stage/s6` |
| 本阶段新增 | 三层 context 记忆、tool_result 内存截断、context_pct、自动 compact、手动 /compact、TUI 上下文水位显示 |
| 依赖上一阶段 | s4 的 Session/thread/notes 模型；s5 的权限与失败分类；s2 的 IPC 事件流 |

## 本阶段要做什么

s5 解决了"工具能不能安全执行"的问题。但一旦 agent 真正开始处理长任务，另一个问题会浮出来：**上下文只会增长，不会自己变短。**

s4 的设计是完整回放。每一轮 chat 都把 `thread.jsonl` 全部读出来，作为 messages 前缀发给 LLM。这个设计保证了连续性，也避免滑动窗口破坏 `tool_use` / `tool_result` 配对。

但完整回放有代价。想象一个真实场景：

```text
分析这个项目，跑测试，修复失败，再总结改动
```

agent 会读很多文件，跑 `pytest -vv`，可能还会 `grep -r`。这些工具结果都会进入 thread。短 demo 里没问题；十几轮之后，LLM 每一步都带着越来越长的历史，直到某一次撞上 context window。

s6 不推翻 s4 的完整回放，而是在它上面加三层治理：

- **进入 prompt 前减负**：超长 `tool_result` 只在内存中截断，`thread.jsonl` 原文不动。
- **调用后看水位**：provider 把 `context_pct` 发布到事件流，TUI 能看到上下文使用率。
- **水位太高时压缩**：自动 compact 改当前 run 的内存 messages；手动 `/compact` 持久化改写 session thread。

同时，s6 把 s4 的 session notes 扩展成三层 context：

```text
~/.kama/context.md               # global: 所有项目共用
<project>/.kama/context.md       # project: 当前仓库约定
~/.kama/sessions/<sid>/notes.md  # session: 当前会话笔记
```

这章按一次长会话的真实路径走：AgentRunner 读取三层 context，SessionStore 读取 thread 时截断大工具结果，provider 发出 usage 水位，AgentLoop 决定是否 compact，TUI 把这一切显示出来。

## S6 上下文治理链路

```
三层 context
(global / project / session)
    │
    ▼
ExecutionContext.system_prompt() ──→ 拼接 Global / Project / Session Notes
    │
    ▼
provider.chat(system + messages)
    ▲
    │          memory 版 messages
    │               ▲
thread.jsonl ──→ SessionStore.read_messages() ──→ truncate_tool_results()
(完整历史原文)           (读出时截断大工具结果)
    │
    ▼
usage ──→ LlmUsageEvent(context_pct)
    │
    ├──→ TUI 显示水位
    │
    └──→ AgentLoop 比较 compact_threshold
              │
              └── 超过阈值 ──→ Compactor 替换当前 run 内存 messages
                                    │
                                    └── context.compacted 事件 ──→ TUI 重置显示
```
