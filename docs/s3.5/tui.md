# TUI 改版：单列终端滚动流

现在切换到用户视角。`kama-tui` 里有什么变化？

整个界面就是一个 `VerticalScroll` 容器，事件进来时动态追加 widget，始终自动滚动到底部。用户按 `ctrl + q` 退出。

---

# LLM 流式输出的原地累积

`KamaTuiApp` 用 `_handle_event_inner` 路由所有到来的事件。收到 `llm.token` 时的处理是这样的：

```python
# tui/app.py

def _handle_event_inner(self, event: dict[str, Any]) -> None:
    t = event.get("type", "")

    if t == "llm.token":
        token = event.get("token", "")
        if self._current_llm is None:
            llm_block = LLMStreamBlock()
            self._append(llm_block)
            self._current_llm = llm_block
        self._current_llm.append_token(token)
        return

    self._break_llm()  # 任何非 token 事件都先结束当前 LLM 块
    ...
```

`LLMStreamBlock` 是一个 `Static` 子类，在同一个 widget 里累积所有 token：

```python
# tui/app.py

class LLMStreamBlock(Static):
    def __init__(self) -> None:
        super().__init__("")
        self._text = ""
        self._finalized = False

    def append_token(self, token: str) -> None:
        self._text += token
        self.update(self._text)

    def finalize_markdown(self) -> None:
        self._finalized = True
        if self._text.strip():
            self.update(Markdown(self._text, code_theme="monokai"))
```

每到一个 token，`self._text` 追加，然后用新字符串刷新 widget 显示。流结束时（收到非 token 事件），`finalize_markdown()` 把累积的文本整体渲染成 Markdown，代码块、列表、粗体都正确显示。

> **为什么不每个 token 追加一个 widget？**
>
> 如果每个 token 都 `mount` 一个新 widget，一次 LLM 回复可能产生几百个 widget 对象，Textual 的布局引擎需要反复计算整个 widget 树的高度和位置，帧率会显著下降，长输出时肉眼可见地卡顿。`update()` 在原地替换内容，布局引擎只需要重绘这一个 widget，代价小得多。

`_current_llm` 是当前"活跃"的 `LLMStreamBlock` 引用。当收到任何非 token 事件时，`_break_llm()` 调用 `finalize_markdown()` 并把引用置为 `None`：下一个 token 到来时会新建一个 `LLMStreamBlock`，形成一个新的文字块。LLM 在不同 step 里的思考内容在视觉上是分隔的，不会混在一起。

---

# 工具调用块的折叠展开

工具调用的显示要解决一个矛盾：工具调用很频繁，但你大多数时候只关心它成功了没有，不需要看完整的参数和输出。把所有内容默认展开会淹没 LLM 的思考文字；全部折叠又让你没有办法深入了解某次调用的细节。

s3 的解法：**默认折叠，点击展开**。

```python
# tui/app.py

class ToolCallBlock(Widget):
    DEFAULT_CSS = """
    ToolCallBlock { height: auto; padding: 0 2; color: $text-muted; }
    ToolCallBlock > .detail { display: none; padding: 0 2 0 4; color: $text-muted; }
    ToolCallBlock.expanded > .detail { display: block; }
    """

    def compose(self) -> ComposeResult:
        yield Static(self._summary(), classes="summary")
        yield Static("", classes="detail")

    def on_click(self) -> None:
        if not self._finished:
            return
        if "expanded" in self.classes:
            self.remove_class("expanded")
        else:
            detail = self.query_one(".detail", Static)
            detail.update(
                f"[dim]params[/dim]\n{self._params_full}\n\n"
                f"[dim]output[/dim]\n{self._output}\n\n"
                f"[dim]elapsed:[/dim] {self._elapsed_ms}ms"
            )
            self.add_class("expanded")
```

`.detail` 这个子 widget 默认是 `display: none` ——存在于 DOM 里，但不占空间、不显示。给父 widget 加上 `expanded` 类后，CSS 规则 `ToolCallBlock.expanded > .detail { display: block; }` 立即生效，detail 出现。

折叠/展开是**纯 CSS 切换**，不需要 `mount / remove` widget，也不需要重新布局整棵树，只是修改显示属性。点击行为很流畅。

工具出错时，摘要行的颜色变红，折叠状态下就能看到出了什么问题——不需要展开细节。

工具输出通过 `ToolCallFinishedEvent.output` 字段传递给 TUI。s3 在这个 event 上新增了 `output: str = ""` 字段，`invoke_tool()` 在 publish 之前把 `result.content` 塞进去，这样 TUI 能直接从事件里拿到工具输出，不需要回查 `events.jsonl`。
