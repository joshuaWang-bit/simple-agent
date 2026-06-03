# S1-Agent 第一次运行

## 第 1 阶段：Agent 第一次运行

| 项目 | 内容 |
|------|------|
| 阶段 | s1 |
| 分支 | `stage/s1` |
| 本阶段新增 | LLM 调用、工具系统、Agent 循环、事件流、CLI run 命令 |
| 依赖上一阶段 | s0 的配置管理（`AgentConfig`）、项目骨架 |

## 本阶段要做什么

s0 结束时我们有一个精致的空壳：配置能读，日志能写，守护进程能启动，然后什么都不发生。

s1 要让它第一次真正"做事"。目标是能执行这条命令：

```bash
# 设置 API Key（硅基流动）
export WIKI_LLM_SILICONFLOW_API_KEY=sk-...

uv run sagent run --goal "总结 README.md 的主要章节"
```

然后在终端看到 agent 实时思考、调工具、输出结果的过程：

```
[run] 20260511-161020-abc123
[step 1] planning...
I'll read the README.md file to get its contents.
[tool] read_file {"path": "README.md"}
[tool] read_file ✓  4ms
[step 1] done
[step 2] planning...
# Summary
The README covers the following sections...
[step 2] done
[run] success  2 steps  5.3s
```

与此同时，`runs/20260511-161020-abc123/events.jsonl` 里会留下整个过程的完整记录，每一步 LLM 做了什么、每次工具调用的结果和耗时，全部可查。

实现这个目标需要解决一连串问题：goal 怎么传给 LLM？LLM 要调工具怎么办？工具出错了继续还是终止？循环什么时候停？执行过程怎么实时显示、怎么持久化？

这些问题环环相扣。我们不会在最开始一次性回答所有问题，而是顺着 `sagent run` 的执行路径一路往下走，问题出现时再解答。
