# 验证

## 单元测试

```
uv run pytest tests/unit -v
```

106 个测试，约 0.7 秒。s2 新增的几个重点测试文件：

- `test_ipc_broadcaster.py`：用 `asyncio.start_server` 在随机端口起临时服务器，测 topic 过滤（`"run.*"` 匹配 `"run.started"`、不匹配 `"step.started"`）、scope 过滤、unsubscribe、死连接清理。全部不需要真实守护进程。
- `test_socket_client.py`：同样起临时服务器，测命令响应路由（Future 被正确 resolve）、`IpcError` 抛出（`"error"` 字段触发 `fut.set_exception`）、事件推送回调、连接断开时所有 pending Future 被 cancel。
- `test_tui_app.py`：用 `_FakeLog`（一个只有 `write()` 方法的简单对象）替代真实的 `RichLog`，绕开 Textual 的渲染层，直接测 `_handle_event()` 的逻辑——token 缓冲、flush 时机、颜色标记。

## 集成测试

```
uv run pytest tests/integration/test_s2_dual_process.py -v
```

三个测试，在真实守护进程上运行，不需要 `ANTHROPIC_API_KEY`（`run.started` 在 LLM provider 初始化之前就推出来了）。

Fixture `running_daemon` 在随机端口启动真实守护进程，轮询等待连接就绪，测试结束后发 SIGTERM 关闭：

```python
@pytest.fixture
async def running_daemon(free_port: int):
    proc = subprocess.Popen(
        [sys.executable, "-m", "kama_claude.core"],
        env={**os.environ, "KAMA_PORT": str(free_port), "KAMA_LOG_LEVEL": "WARNING"},
    )
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        await asyncio.sleep(0.05)
        try:
            _, w = await asyncio.open_connection("127.0.0.1", free_port)
            w.close(); break
        except (ConnectionRefusedError, OSError):
            pass
    yield proc
    proc.terminate(); proc.wait(timeout=2)
```

**test 1**：发 `agent.run`，5 秒内收到 `run.started`，且事件里的 `run_id` 与命令返回的一致。

**test 2**：两个客户端同时订阅，一个触发 `agent.run`，验证两个客户端都收到 `run.started`。用 `asyncio.gather` 并行等待两个事件：

```python
await asyncio.wait_for(
    asyncio.gather(event1.wait(), event2.wait()),
    timeout=5.0,
)
```

**test 3**：client1 触发 run、等到 `run.started` 后断开；client2 用 `replay_from_run=run_id` 重连，验证 `replayed_count > 0` ——确认事件落盘和回放的完整闭环。

## 手动验证

```bash
# 终端 A：前台启动守护进程
uv run kama-core

# 终端 B：打开 TUI（先开）
uv run kama-tui

# 终端 C：触发一次 run
uv run kama run --goal "用一句话介绍你自己"
```

终端 B 的 TUI 和终端 C 的 CLI 应该同时滚动出事件流——这是 s1 做不到的，是 s2 的核心交付。
