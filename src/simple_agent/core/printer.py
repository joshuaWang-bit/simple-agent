from typing import Any


class StdoutPrinter:
    def handle(self, event: Any) -> None:
        if isinstance(event, dict):
            t = event.get("type", "")
            run_id = event.get("run_id", "")
        else:
            t = getattr(event, "type", "")
            run_id = getattr(event, "run_id", "")

        match t:
            case "run.started":
                goal = event.get("goal", "") if isinstance(event, dict) else getattr(event, "goal", "")
                print(f"[run] {run_id} {goal}")
            case "step.started":
                step = event.get("step", 0) if isinstance(event, dict) else getattr(event, "step", 0)
                print(f"[step {step}] planning...")
            case "llm.token":
                token = event.get("token", "") if isinstance(event, dict) else getattr(event, "token", "")
                print(token, end="", flush=True)
            case "tool.call_started":
                tool_name = event.get("tool_name", "") if isinstance(event, dict) else getattr(event, "tool_name", "")
                input_data = event.get("input", {}) if isinstance(event, dict) else getattr(event, "input", {})
                print(f"\n[tool] {tool_name} {input_data}")
            case "tool.call_finished":
                tool_name = event.get("tool_name", "") if isinstance(event, dict) else getattr(event, "tool_name", "")
                elapsed_ms = event.get("elapsed_ms", 0) if isinstance(event, dict) else getattr(event, "elapsed_ms", 0)
                print(f"[tool] {tool_name} ✓  {elapsed_ms}ms")
            case "step.finished":
                step = event.get("step", 0) if isinstance(event, dict) else getattr(event, "step", 0)
                print(f"\n[step {step}] done")
            case "run.finished":
                status = event.get("status", "") if isinstance(event, dict) else getattr(event, "status", "")
                step_count = event.get("step_count", 0) if isinstance(event, dict) else getattr(event, "step_count", 0)
                elapsed_s = event.get("elapsed_s", 0.0) if isinstance(event, dict) else getattr(event, "elapsed_s", 0.0)
                reason = event.get("reason", None) if isinstance(event, dict) else getattr(event, "reason", None)
                if status == "success":
                    print(f"[run] success  {step_count} steps  {elapsed_s:.1f}s")
                else:
                    print(f"[run] {reason or status}  {step_count} steps  {elapsed_s:.1f}s")
