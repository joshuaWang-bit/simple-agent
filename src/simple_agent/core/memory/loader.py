from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_context_file(path: Path) -> str:
    p = path.expanduser()
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.warning("failed to read context file %s: %s", p, exc)
        return ""
