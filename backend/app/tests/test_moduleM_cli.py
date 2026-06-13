from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.tests.test_config_schema import FIXTURE_DIR

REPO_ROOT = Path(__file__).resolve().parents[3]


class FakeEpisodeResult:
    episode_id = "E-cli"
    status = "completed"
    final_time_s = 1.0
    final_frame_index = 2


class FakeRunner:
    def run_episode(self) -> FakeEpisodeResult:
        return FakeEpisodeResult()


def _run_script(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(REPO_ROOT / ".venv" / "bin" / "python"), str(REPO_ROOT / script), *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_help_commands_return_zero() -> None:
    for script in [
        "scripts/run_episode.py",
        "scripts/replay_episode.py",
        "scripts/batch_generate.py",
    ]:
        result = _run_script(script, "--help")
        assert result.returncode == 0, result.stderr
        assert "usage:" in result.stdout


def test_run_episode_function_outputs_json_with_fake_runner_factory() -> None:
    from backend.app.api.cli import run_episode_from_config

    result = run_episode_from_config(
        FIXTURE_DIR / "demo_valid.yaml",
        output_json=True,
        runner_factory=lambda **kwargs: FakeRunner(),
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["episode_id"] == "E-cli"
    assert payload["status"] == "completed"
    assert "run_dir" in payload


def test_run_episode_script_runs_with_default_runner_factory(tmp_path: Path) -> None:
    result = _run_script(
        "scripts/run_episode.py",
        "--config",
        str(FIXTURE_DIR / "demo_valid.yaml"),
        "--output-json",
        "--override",
        f"experiment.output.run_root={tmp_path}",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["episode_id"] == "cli-episode"
    assert payload["status"] in {"completed", "timeout"}
    assert payload["run_dir"]
    assert payload["final_frame_index"] > 0
    summary_path = Path(payload["summary_path"])
    assert summary_path.is_file()
    assert summary_path.name == "episode_summary.json"
    frames_path = Path(payload["run_dir"]) / "visual" / "frames.jsonl"
    assert frames_path.is_file()
    first_frame = json.loads(frames_path.read_text(encoding="utf-8").splitlines()[0])
    assert first_frame["type"] == "sim_frame"


def test_run_episode_missing_config_returns_exit_code_1() -> None:
    result = _run_script("scripts/run_episode.py", "--config", "missing.yaml")

    assert result.returncode == 1
    assert "configuration file not found" in result.stderr


def test_replay_episode_missing_replay_file_returns_exit_code_3(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    result = _run_script("scripts/replay_episode.py", "--run", str(run_dir))

    assert result.returncode == 3
    assert "command_replay.jsonl" in result.stderr


def test_batch_generate_not_implemented_returns_exit_code_4() -> None:
    result = _run_script(
        "scripts/batch_generate.py",
        "--config",
        str(FIXTURE_DIR / "dataset_valid.yaml"),
    )

    assert result.returncode == 4
    assert "not implemented" in result.stderr.lower()


def test_batch_generate_rejects_zero_max_episodes() -> None:
    result = _run_script(
        "scripts/batch_generate.py",
        "--config",
        str(FIXTURE_DIR / "dataset_valid.yaml"),
        "--max-episodes",
        "0",
    )

    assert result.returncode == 1
    assert "max-episodes" in result.stderr


def test_cli_scripts_do_not_import_fastapi_app() -> None:
    for script in [
        REPO_ROOT / "scripts" / "run_episode.py",
        REPO_ROOT / "scripts" / "replay_episode.py",
        REPO_ROOT / "scripts" / "batch_generate.py",
    ]:
        text = script.read_text(encoding="utf-8")
        assert "backend.app.main" not in text
        assert "create_app" not in text
