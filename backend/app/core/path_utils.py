from __future__ import annotations

from pathlib import Path
from typing import Union


PathLike = Union[str, Path]


class PathSecurityError(ValueError):
    def __init__(self, path: PathLike, root: PathLike) -> None:
        self.path = str(path)
        self.root = str(root)
        super().__init__(f"path '{path}' escapes allowed root '{root}'")


def normalize_path_under_root(path: PathLike, root: PathLike) -> Path:
    root_path = Path(root).expanduser().resolve()
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = root_path / candidate
    resolved = candidate.resolve()
    if resolved != root_path and root_path not in resolved.parents:
        raise PathSecurityError(path, root_path)
    return resolved
