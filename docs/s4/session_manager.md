# SessionManager：daemon 里的会话入口

`SocketServer` 收到 `session.create` 后，最终会走到 `CoreApp` 的 handler：

```python
# src/simple_agent/core/app.py（节选）

async def _session_create_handler(self, params: dict[str, Any]) -> SessionCreateResult:
    cmd = SessionCreateCommand.model_validate(params)
    session = await self._sessions.create(mode=cmd.mode, title=cmd.title)
    return SessionCreateResult(session_id=session.id, status=session.status)
```

这里的 `_sessions` 就是 s4 新增的 `SessionManager`。创建 session 时，它生成一个 `sess-` 开头的 ID，写一份 `meta.json`，再发布 `session.created`：

```python
# src/simple_agent/core/session/manager.py（节选）

async def create(self, mode: SessionMode, title: str = "") -> Session:
    sid = f"sess-{uuid.uuid4().hex[:12]}"
    ts = _now()
    session = Session(
        id=sid,
        mode=mode,
        status="active",
        title=title,
        created_at=ts,
        updated_at=ts,
        run_ids=[],
    )
    self._sessions[sid] = session
    self._locks[sid] = asyncio.Lock()
    self._store.write_meta(session)
    await self._bus.publish(SessionCreatedEvent(session_id=sid, mode=mode, ts=ts))
    return session
```

磁盘上，一个 session 是这样的：

```
~/.sagent/sessions/sess-9f3a2c1b8d04/
    meta.json
    thread.jsonl
    notes.md
    runs/
      20260519-103012-a1b2c3/
        events.jsonl
        .tasks/
```

`meta.json` 是 session 档案：ID、模式、状态、标题、创建时间、更新时间、包含哪些 run。`runs/` 下面仍然是 s1/s2/s3 熟悉的 run 目录，只是它们现在归属到一个 session 下。

为什么不继续把 run 写到当前项目的 `runs/` 目录？

s2 之后 daemon 是一个全局服务。你可以从任意工作目录连接它。如果数据还散在各个项目目录里，session 就很难统一管理。s4 把会话数据集中到 `~/.sagent/sessions/`，和 `~/.sagent/config.toml`、`~/.sagent/logs/` 放在同一个用户级空间里。

> 💡 s4 开始，run 不再是顶层概念。run 是 session 里的一个回合，session 才是用户连续协作的容器。

## 第一条消息：先写 thread，再启动 run

用户在 chat 里输入：

```
项目用什么 Python 版本？
```

CLI 发出：

```json
{"method":"session.send_message","params":{"session_id":"sess-...","content":"项目用什么 Python 版本？"}}
```

daemon 侧的主逻辑在 `SessionManager.send_message`：

```python
# src/simple_agent/core/session/manager.py（节选）

async def send_message(self, sid: str, content: str, *, run_id: str | None = None) -> str:
    session = self._get_session(sid)
    lock = self._locks[sid]
    if lock.locked():
        raise HandlerError(SESSION_BUSY, "session busy")

    async with lock:
        if session.status == "closed":
            raise HandlerError(SESSION_CLOSED, "session already closed")

        if session.status == "waiting_for_input":
            await self._bus.publish(SessionResumedEvent(session_id=sid, ts=_now()))

        self._store.append_message(sid, "user", content)
        await self._bus.publish(SessionMessageReceivedEvent(...))

        run_id = run_id or new_run_id()
        session.run_ids.append(run_id)
        self._store.write_meta(session)

        runner = self._runner_factory()
        await runner.run_and_capture(
            content,
            run_id=run_id,
            session=session,
            store=self._store,
        )
        ...
```

最重要的是这句：

```python
self._store.append_message(sid, "user", content)
```

**用户消息必须先写进 `thread.jsonl`，再启动 AgentRunner。**

原因很直接：AgentRunner 接下来会读取整个 thread 作为 LLM 的 messages 前缀。如果这条 user 消息还没写进去，LLM 就看不到用户本轮到底问了什么。

这里也引入了每个 session 一把 `asyncio.Lock`。如果同一个 session 正在跑，用户又发来第二条消息，系统直接返回 `session busy`，而不是排队。

为什么不排队？因为 agent 的下一轮应该建立在上一轮完整结果上。上一轮还没结束时，thread 和 notes 都没稳定，提前排队只会制造更难理解的状态。`busy` 是更清晰的语义：等 `[waiting for input]` 再发下一句。

## `sagent run` 仍然可用：one_shot session

s4 引入 session 后，还有一个兼容问题：原来的 `sagent run --goal ...` 怎么办？

我们不希望老命令突然变成另一套执行路径。s4 的做法是：让 `agent.run` 在 daemon 内部创建一个 `one_shot` session，然后调用同一个 `SessionManager.send_message`。

```python
# src/simple_agent/core/app.py（节选）

async def _agent_run_handler(self, params):
    cmd = AgentRunCommand.model_validate(params)
    session = await self._sessions.create(mode="one_shot", title=cmd.goal[:40])
    run_id = new_run_id()
    run_task = asyncio.create_task(
        self._sessions.send_message(session.id, cmd.goal, run_id=run_id)
    )
    self._running_runs.add(run_task)
    run_task.add_done_callback(self._running_runs.discard)
    return AgentRunResult(run_id=run_id)
```

`one_shot` 和 `chat` 的区别只在 run 结束之后：

- `chat`：进入 `waiting_for_input`，继续等下一条消息。
- `one_shot`：进入 `closed`，行为上仍然像一次性 run。

这样 `sagent run`、TUI 里已有的订阅逻辑、`events.jsonl` 都不用重写。只是底层存储统一到了 `~/.sagent/sessions/<sid>/runs/<run_id>/`。

> 💡 这是渐进迁移。强制所有客户端立刻改成 `session.create + session.send_message` 也能做，但会同时改 CLI、TUI、测试和用户习惯。one_shot session 让新模型先落地，旧入口继续工作。
