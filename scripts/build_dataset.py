from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.api.cli import main_build_dataset


if __name__ == "__main__":
    raise SystemExit(main_build_dataset())
