from __future__ import annotations

import tomllib
from pathlib import Path


def test_desktop_runtime_declares_uvicorn_dependency() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    dependencies = pyproject["project"]["dependencies"]

    assert any(dependency.lower().startswith("uvicorn") for dependency in dependencies)
