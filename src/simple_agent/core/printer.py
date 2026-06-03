from pydantic import BaseModel


class StdoutPrinter:
    def handle(self, event: BaseModel) -> None:
        t = getattr(event, "type", "")
        match t:
            case "run.started":
                print(f"[run] {event.run_id}")
            case "step.started":
                print(f"[step {event.step}] planning...")
            case "llm.token":
                print(event.token, end="", flush=True)
            case "tool.call_started":
                print(f"\n[tool] {event.tool_name} {event.input}")
            case "tool.call_finished":
                print(f"[tool] {event.tool_name} ✓  {event.elapsed_ms}ms")
            case "step.finished":
                print(f"\n[step {event.step}] done")
            case "run.finished":
                status = "success" if event.status == "success" else event.reason
                print(f"[run] {status}  {event.step_count} steps  {event.elapsed_s:.1f}s")
