# 参数先过 pydantic

权限审批不是第一道关。第一道关是参数格式。

如果 LLM 调了：

```json
{"name":"bash","input":{"timeout":-1}}
```

这不是一个需要用户判断"允不允许"的问题，而是 LLM 给错了参数。应该立刻返回 `schema_error`，让 LLM 修正。

## 给工具增加 params_model

s5 给工具增加了可选的 `params_model`：

```python
# core/tools/builtin/bash.py（节选）

class BashParams(BaseModel):
    model_config = ConfigDict(extra="ignore")
    command: str
    timeout: int = Field(default=60, ge=1, le=120)


class BashTool(BaseTool):
    params_model = BashParams
```

`params_model` 是一个普通的 pydantic `BaseModel`。`extra="ignore"` 表示 LLM 可能多传一些不认识的字段，直接忽略，不报错。`Field(ge=1, le=120)` 把 `timeout` 限制在 1 到 120 秒之间。

## invoke_tool 的校验顺序

`invoke_tool()` 在权限检查之前校验：

```python
# core/tools/invocation.py（节选）

if tool.params_model is not None:
    try:
        tool.params_model.model_validate(dict(tool_call.input))
    except ValidationError as exc:
        return await _fail(
            bus, run_id, tool_call,
            "schema_error", str(exc), elapsed(),
        )
```

这个顺序很重要。参数错了就不要弹审批卡片。用户看到一张写着 `timeout=-1` 的审批卡片，很难知道应该按允许还是拒绝；更好的反馈对象是 LLM 自己。

> 💡 `schema_error` 是给 agent 的纠错信号，不是给用户的决策请求。
