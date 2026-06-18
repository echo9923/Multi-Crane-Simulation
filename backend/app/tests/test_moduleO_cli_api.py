from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.tests.test_config_schema import FIXTURE_DIR, load_fixture
from backend.app.tests.test_dataset_builder import _episode

REPO_ROOT = Path(__file__).resolve().parents[3]


def _dataset_config_file(tmp_path: Path) -> Path:
    raw = load_fixture("dataset_valid.yaml")
    raw["sources"] = [
        {
            "scenario_ref": str(FIXTURE_DIR / "scenario_valid.yaml"),
            "experiment_template_ref": str(FIXTURE_DIR / "experiment_valid.yaml"),
            "num_episodes": 2,
        }
    ]
    raw["windows"] = {
        "input_steps": 2,
        "pred_steps": 2,
        "stride_steps": 2,
        "risk_label_horizons_s": [5, 10],
        "negative_positive_sampling": {
            "enabled": False,
            "max_negative_to_positive_ratio": 5,
        },
    }
    raw["split"]["holdout"] = {"unseen_layout": False, "unseen_num_cranes": False}
    path = tmp_path / "dataset.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def test_build_dataset_function_outputs_json_and_api_reads_summary(tmp_path: Path) -> None:
    from backend.app.api.cli import build_dataset_from_config

    source_root = tmp_path / "runs"
    _episode(source_root, "E001", high=True)
    _episode(source_root, "E002")
    output_root = tmp_path / "datasets"

    result = build_dataset_from_config(
        _dataset_config_file(tmp_path),
        source_roots=[source_root],
        output_root=output_root,
        copy_mode="index_only",
        output_json=True,
    )

    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["dataset_id"] == "tower_crane_llm_dataset_v1"
    assert payload["num_episodes"] == 2
    assert payload["summary_path"].endswith("dataset_summary.json")

    app = create_app()
    app.state.dataset_root = output_root
    client = TestClient(app)
    list_response = client.get("/datasets")
    summary_response = client.get("/datasets/tower_crane_llm_dataset_v1/summary")

    assert list_response.status_code == 200
    assert list_response.json()["data"]["items"][0]["dataset_id"] == payload["dataset_id"]
    assert summary_response.status_code == 200
    assert summary_response.json()["data"]["summary"]["num_episodes"] == 2


def test_build_dataset_rejects_missing_source_root(tmp_path: Path) -> None:
    from backend.app.api.cli import build_dataset_from_config

    result = build_dataset_from_config(
        _dataset_config_file(tmp_path),
        source_roots=[tmp_path / "missing"],
        output_root=tmp_path / "datasets",
        output_json=True,
    )

    assert result.exit_code == 4
    assert "DATASET_E_SOURCE_NOT_FOUND" in result.stderr


def test_build_dataset_script_help_returns_zero() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "build_dataset.py"),
            "--help",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "usage:" in result.stdout
