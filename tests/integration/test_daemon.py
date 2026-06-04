import asyncio
import sys
from pathlib import Path

# Add src to path so simple_agent can be imported
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from simple_agent.core.app import CoreApp
from simple_agent.core.llm.provider import LlmResponse


class FakeProvider:
    async def chat(
        self,
        messages,
        tool_schemas,
        bus,
        run_id,
        *,
        step=0,
    ):
        await asyncio.sleep(0.1)
        return LlmResponse(text="done", stop_reason="end_turn")


if __name__ == "__main__":
    app = CoreApp(provider=FakeProvider())
    asyncio.run(app.run())
