from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    system_prompt_template: str
    allowed_tools: list[str]
    path: Path


class SkillLoader:
    def __init__(
        self,
        *,
        project_dir: Path | None = None,
        home_dir: Path | None = None,
        builtin_dir: Path | None = None,
    ) -> None:
        self._project_dir = project_dir or Path.cwd()
        self._home_dir = home_dir or Path.home()
        self._builtin_dir = builtin_dir or Path(__file__).with_name("builtin")

    def resolve(self, name: str) -> Skill | None:
        safe_name = _safe_name(name)
        if safe_name is None:
            return None

        for base in self._search_dirs():
            path = base / f"{safe_name}.md"
            if path.exists():
                return self._load(path, fallback_name=safe_name)
        return None

    def render_prompt(self, skill: Skill, arguments: str) -> str:
        return skill.system_prompt_template.replace("$ARGUMENTS", arguments).strip()

    def _search_dirs(self) -> list[Path]:
        return [
            self._project_dir / ".sagent" / "skills",
            self._project_dir / ".kama" / "skills",
            self._home_dir / ".sagent" / "skills",
            self._home_dir / ".kama" / "skills",
            self._builtin_dir,
        ]

    def _load(self, path: Path, *, fallback_name: str) -> Skill:
        raw = path.read_text(encoding="utf-8")
        metadata, body = _split_frontmatter(raw)
        name = str(metadata.get("name") or fallback_name)
        description = str(metadata.get("description") or "")
        allowed = metadata.get("allowed_tools") or []
        if not isinstance(allowed, list):
            allowed = []
        return Skill(
            name=name,
            description=description,
            system_prompt_template=body.strip(),
            allowed_tools=[str(item) for item in allowed],
            path=path,
        )


def _safe_name(name: str) -> str | None:
    if not name:
        return None
    if any(ch in name for ch in ("/", "\\", ".", ":")):
        return None
    return name


def _split_frontmatter(raw: str) -> tuple[dict[str, object], str]:
    if not raw.startswith("---\n"):
        return {}, raw

    end = raw.find("\n---\n", 4)
    if end == -1:
        return {}, raw

    front = raw[4:end]
    body = raw[end + 5 :]
    return _parse_simple_yaml(front), body


def _parse_simple_yaml(text: str) -> dict[str, object]:
    result: dict[str, object] = {}
    current_list_key: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("- ") and current_list_key is not None:
            items = result.setdefault(current_list_key, [])
            if isinstance(items, list):
                items.append(_unquote(stripped[2:].strip()))
            continue

        current_list_key = None
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not value:
            result[key] = []
            current_list_key = key
        elif value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            result[key] = [
                _unquote(item.strip()) for item in inner.split(",") if item.strip()
            ]
        else:
            result[key] = _unquote(value)
    return result


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value
