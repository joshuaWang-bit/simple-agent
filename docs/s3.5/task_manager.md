# AgentRunner 接入 TaskManager

进入 `AgentRunner.run_and_capture()`，s3 在这里加了两行关键代码：

```python
# core/runner.py

async def run_and_capture(self, goal: str, *, run_id: str | None = None) -> RunOutcome:
    run_id = run_id or new_run_id()
    run_path = self._runs_dir / run_id
    run_path.mkdir(parents=True, exist_ok=True)

    task_manager = TaskManager(run_path / ".tasks")  # [new]
    ...
    registry = self._build_registry(task_manager)     # [new]
    loop = AgentLoop(provider, registry, bus)
    ...
```

`TaskManager` 的初始化路径是 `runs/<run_id>/.tasks/` ——每个 run 的任务数据完全隔离，互不干扰，可以随时回溯某次 run 的完整规划记录。

`_build_registry(task_manager)` 把 4 个任务工具和这个 `task_manager` 实例一起注册进工具注册表：

```python
# core/runner.py

def _build_registry(self, task_manager: TaskManager) -> ToolRegistry:
    registry = ToolRegistry()
    for t in [ReadFileTool(), BashTool(), WriteFileTool(), ListDirTool()]:
        registry.register(t)
    for t in [
        TaskCreateTool(task_manager),
        TaskUpdateTool(task_manager),
        TaskListTool(task_manager),
        TaskGetTool(task_manager),
    ]:
        registry.register(t)
    return registry
```

所有 4 个任务工具共享同一个 `task_manager` 实例。这是关键：`task_create` 写入的文件，`task_update` 和 `task_list` 能读到，因为它们操作的是同一个 `.tasks/` 目录下的同一批 JSON 文件。

---

# TaskManager：同步的文件 CRUD

`TaskManager` 是 s3 任务系统的核心，但它有意做得很简单：

```python
# core/task/manager.py

class TaskManager:
    def __init__(self, tasks_dir: Path) -> None:
        self._dir = tasks_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._next_id = self._max_id() + 1

    def create(self, subject: str, description: str = "", blocked_by: list[int] | None = None):
        ...
        task = Task(id=self._next_id, subject=subject, ..., blocked_by=list(blocked_by or []))
        self._save(task)          # 直接写 JSON 文件
        self._next_id += 1
        return task

    def update(self, task_id: int, *, status, add_blocked_by, remove_blocked_by) -> Task:
        task = self._load(task_id)       # 读文件
        if status == "completed":
            self._clear_dependency(task_id)    # 自动解除其他任务的阻塞
        ...
        self._save(task)          # 写回文件
        return task
```

`TaskManager` 没有异步方法，没有 EventBus 依赖，没有状态机。它是**纯粹的同步文件 CRUD 层**，每次操作就是读一个 JSON 文件、改一改、写回去。

为什么不用数据库？任务数量通常是个位数到十几个，文件 I/O 的开销完全可以忽略。用文件的好处是：任务的完整历史可以直接用 `ls` 和 `cat` 查看，不需要任何工具，调试非常方便。

> **ID 用整数，不用 UUID**
>
> 工具 schema 里 `task_id` 是 `integer`，调用 `task_update` 时参数是 `{"task_id": 1}`。如果用 UUID，LLM 需要先记住完整的随机字符串，再在下一个工具调用里原样复述，出错概率高得多。整数 ID 在对话历史里不占位置，LLM 几乎不会用错。

每个任务持久化为一个独立 JSON 文件：

```json
{
  "id": 1,
  "subject": "分析目录结构",
  "description": "了解整体布局，找出核心模块",
  "status": "completed",
  "blocked_by": [],
  "created_at": "2026-05-19T10:00:01Z",
  "updated_at": "2026-05-19T10:00:45Z"
}
```

状态只有三种：`pending`（等待）、`in_progress`（进行中）、`completed`（完成）。没有 pause、retry、cancel——这些是流程控制逻辑，不是任务本身的状态。agent 如果需要重试，直接用工具再做一遍就好了。

---

# blocked_by 的自动级联

任务依赖关系用 `blocked_by` 字段表示：`task_2.blocked_by = [1]` 意味着任务 2 在等待任务 1 完成才能开始。

当 LLM 把任务 1 标记为 `completed`，`_clear_dependency(1)` 会扫描 `.tasks/` 目录下所有文件，把 `blocked_by` 里含有 `1` 的条目全部移除——不需要 LLM 手动去更新依赖关系，直接就解锁了。

```python
# core/task/manager.py

def _clear_dependency(self, completed_id: int) -> None:
    for f in self._dir.glob("task_*.json"):
        data = json.loads(f.read_text())
        blocked = [int(x) for x in data.get("blocked_by", [])]
        if completed_id in blocked:
            data["blocked_by"] = [x for x in blocked if x != completed_id]
            data["updated_at"] = _now()
            f.write_text(json.dumps(data, indent=2, ensure_ascii=False))
```

这个设计让 LLM 的操作序列非常自然：创建任务时声明依赖，完成任务时只需更新自己的状态，其他任务的解锁是自动发生的副作用。
