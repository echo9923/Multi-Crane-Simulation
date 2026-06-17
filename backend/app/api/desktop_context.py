from __future__ import annotations

from pathlib import Path
from typing import Any


def resolve_desktop_project_root(app_or_state: Any) -> Path:
    state = getattr(app_or_state, "state", app_or_state)
    root = getattr(state, "project_root", None)
    if root is None:
        return Path.cwd().resolve()
    return Path(root).expanduser().resolve()
