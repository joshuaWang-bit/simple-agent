#!/usr/bin/env python3
"""Generate WIRE_PROTOCOL.md from pydantic models."""
from __future__ import annotations

import argparse
import inspect
import json
import sys
from pathlib import Path

from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_PATH = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_PATH))

import simple_agent.core.bus.commands as commands_mod  # noqa: E402
import simple_agent.core.bus.events as events_mod  # noqa: E402


def _collect_models(module) -> list[type[BaseModel]]:
    models = []
    for name, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, BaseModel) and obj is not BaseModel:
            models.append(obj)
    return models


def _model_section(model: type[BaseModel]) -> str:
    lines = [f"### `{model.__name__}`\n"]
    lines.append("**Fields:**\n")
    for name, field in model.model_fields.items():
        annotation = field.annotation
        default = field.default
        if default is not None and default is not ...:
            lines.append(f"- `{name}`: `{annotation}` = `{default}`")
        else:
            lines.append(f"- `{name}`: `{annotation}`")
    lines.append("")
    lines.append("**JSON Schema:**")
    lines.append("```json")
    schema = model.model_json_schema()
    lines.append(json.dumps(schema, indent=2, ensure_ascii=False))
    lines.append("```")
    lines.append("")
    try:
        example = model.model_construct()
        lines.append("**Example:**")
        lines.append("```json")
        lines.append(json.dumps(example.model_dump(mode="json"), indent=2, ensure_ascii=False))
        lines.append("```")
    except Exception:
        pass
    lines.append("")
    return "\n".join(lines)


def generate() -> str:
    lines = [
        "# Wire Protocol\n",
        "> Auto-generated from bus models. Do not edit manually.\n",
    ]

    lines.append("## Commands\n")
    for model in _collect_models(commands_mod):
        lines.append(_model_section(model))

    lines.append("## Events\n")
    for model in _collect_models(events_mod):
        lines.append(_model_section(model))

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true", help="Check if file is up to date"
    )
    args = parser.parse_args()

    content = generate()
    output_path = PROJECT_ROOT / "WIRE_PROTOCOL.md"

    if args.check:
        if output_path.exists():
            existing = output_path.read_text(encoding="utf-8")
            if existing == content:
                print("WIRE_PROTOCOL.md is up to date")
                sys.exit(0)
        print("WIRE_PROTOCOL.md is out of date")
        sys.exit(1)
    else:
        output_path.write_text(content, encoding="utf-8")
        print(f"Generated {output_path}")


if __name__ == "__main__":
    main()
