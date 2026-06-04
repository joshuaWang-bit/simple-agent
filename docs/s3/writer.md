# TraceWriter：队列 + 后台写入

```python
# core/trace/writer.py

class TraceWriter:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._queue: asyncio.Queue[TraceRecord] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._task = asyncio.create_task(self._drain())

    async def stop(self) -> None:
        await self._queue.join()   # 等队列里的记录全部写完
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def emit(self, record: TraceRecord) -> None:
        self._queue.put_nowait(record)   # 同步，不阻塞

    async def _drain(self) -> None:
        with open(self._path, "a") as f:
            while True:
                record = await self._queue.get()
                try:
                    f.write(record.model_dump_json() + "\n")
                    f.flush()
                finally:
                    self._queue.task_done()
```

`stop()` 先 `await self._queue.join()` 再取消 drain task，而不是直接取消。这确保了 daemon 退出时队列里的最后几条记录都能落盘——`task_done()` 在 `finally` 块里调用，即使 `f.write()` 抛异常也会执行，`join()` 不会永久阻塞。
