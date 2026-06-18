from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_deepseek_demo_script_runs_production_with_venv_python() -> None:
    script = REPO_ROOT / "scripts" / "run_deepseek_demo.sh"

    assert script.is_file()
    if os.name != "nt":
        assert script.stat().st_mode & 0o111

    content = script.read_text(encoding="utf-8")
    assert ".venv/bin/python" in content
    assert "scripts/run_episode.py" in content
    assert "configs/deepseek_demo_4x2_manual.yaml" in content
    assert "--runner production" in content
    assert "--output-json" in content


def test_deepseek_demo_script_packages_frontend_import_zip() -> None:
    content = (
        REPO_ROOT / "scripts" / "run_deepseek_demo.sh"
    ).read_text(encoding="utf-8")

    assert "--package-latest" in content
    assert "visual/frames.jsonl" in content
    assert "visual/episode_manifest.json" in content
    assert "logs/commands.jsonl" in content
    assert "logs/events.jsonl" in content
    assert "logs/llm_decisions.jsonl" in content
    assert "logs/llm_observations.jsonl" in content
    assert "metadata/episode_summary.json" in content
    assert "deepseek-real-flow-import.zip" in content


def test_deepseek_demo_script_shows_live_terminal_dashboard_by_default() -> None:
    content = (
        REPO_ROOT / "scripts" / "run_deepseek_demo.sh"
    ).read_text(encoding="utf-8")

    assert "live dashboard" in content.lower()
    assert "render_dashboard" in content
    assert "task_stage" in content
    assert "hook_h_m" in content
    assert "theta_rad" in content
    assert "trolley_r_m" in content
    assert "load_attached" in content
    assert "llm_decisions.jsonl" in content
