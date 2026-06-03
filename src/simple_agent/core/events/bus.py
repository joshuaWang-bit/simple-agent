import inspect
from typing import Any, Callable

from pydantic import BaseModel

EventHandler = Callable[[BaseModel], Any]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[EventHandler] = []

    def subscribe(self, handler: EventHandler) -> None:
        self._subscribers.append(handler)

    async def publish(self, event: BaseModel) -> None:
        for handler in self._subscribers:
            result = handler(event)
            if inspect.isawaitable(result):
                await result
