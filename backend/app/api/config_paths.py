from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.app.api.desktop_context import resolve_desktop_project_root
from backend.app.core.path_utils import normalize_path_under_root


def resolve_config_path_for_request(path: str, app_or_state: Any) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return normalize_path_under_root(candidate, resolve_desktop_project_root(app_or_state))


__all__ = ["resolve_config_path_for_request"]
