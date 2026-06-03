# 命令行入口

用户输入 `sagent run --goal "..."` 回车之后，最先跑起来的是 `cli/main.py`。它用 Python 标准库的 `argparse` 解析命令行参数，然后把控制权交给对应的子命令处理函数：

```python
# cli/main.py（节选）

config = get_config()   # 读取配置（s0 已实现）

if args.command == "run":
    if args.tier:
        config.llm_tier = args.tier
    cmd_run(args.goal, config)
```

`get_config()` 负责按优先级加载配置（默认值 → TOML 文件 → `.env` → 环境变量），这是 s0 已经建好的基础设施，这里直接用。`--tier` 可以在命令行临时覆盖配置里的 `llm_tier`。

进入 `cmd_run`：

```python
# cli/commands/run.py

def cmd_run(goal: str, config: AgentConfig) -> None:
    printer = StdoutPrinter()
    runner = AgentRunner(config, extra_handlers=[printer.handle])
    try:
        asyncio.run(runner.run(goal))
    except KeyboardInterrupt:
        sys.exit(130)
```

这里做了三件事：创建负责打印终端输出的 `StdoutPrinter`，创建负责组装所有零件的 `AgentRunner`，然后用 `asyncio.run()` 启动异步运行。

`asyncio.run()` 的作用是启动一个事件循环并运行传入的协程。我们的 agent 需要同时等待网络请求（调用 LLM API）和文件 I/O，用异步的方式可以在等待一件事的时候去做另一件事，而不是傻等着。你可以把 `asyncio.run()` 理解为"开始干活"的发令枪。

`KeyboardInterrupt` 对应用户按 Ctrl+C，退出码 130 是 Unix 的约定（128 + SIGINT 信号编号 2），这样调用 `sagent` 的脚本就能识别出"是被用户中断的"。
