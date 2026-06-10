# TUI：从只读窗口变成可输入会话

s3 的 TUI 只能看。它订阅事件，展示 run 过程，但用户要继续对话还得回 CLI。

s4 给 TUI 底部加了输入框。输入框提交后，走的就是上面介绍过的 `session.send_message`，和 `sagent chat` 底层完全相同。

这里没有直接用 Textual 的 `Input`，而是用 `TextArea` 包了一层：

```python
# src/simple_agent/tui/app.py（节选）

class ChatTextArea(TextArea):
    class Submitted(Message):
        def __init__(self, area):
            self.text_area = area
            self.value = area.text
            super().__init__()

    async def _on_key(self, event):
        key = event.key
        if key == "enter":
            event.stop()
            event.prevent_default()
            if self.text.strip():
                self.post_message(self.Submitted(self))
            return
        if key in ("alt+enter", "shift+enter", "ctrl+j", "super+enter"):
            event.stop()
            event.prevent_default()
            if not self.read_only:
                self.insert("\n")
            return
        await super()._on_key(event)
```

选择 `TextArea` 是因为用户可能输入多行内容。语义是：

- Enter：提交
- Shift/Alt/Cmd+Enter：换行

如果用默认 `TextArea` 行为，Enter 会插入换行；如果用 `Input`，又没有多行能力。这里定制按键处理，就是为了让 TUI 更像一个真正的 chat 输入框。

输入提交后，TUI 也会在 run 进行中禁用输入框，等收到 `session.waiting_for_input` 再重新启用。这和 CLI 的 `[waiting for input]` 是同一个状态，只是呈现方式不同。
