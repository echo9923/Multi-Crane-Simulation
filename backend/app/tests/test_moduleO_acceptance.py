from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
import yaml
from fastapi.testclient import TestClient

from backend.app.api.cli import build_dataset_from_config
from backend.app.main import create_app
from backend.app.schemas.dataset import DatasetWindowIndexRow
from backend.app.tests.test_config_schema import FIXTURE_DIR, load_fixture
from backend.app.tests.test_dataset_builder import _episode


def _dataset_config_file(tmp_path: Path) -> Path:
    raw = load_fixture("dataset_valid.yaml")
    raw["sources"] = [
        {
            "scenario_ref": str(FIXTURE_DIR / "scenario_valid.yaml"),
            "experiment_template_ref": str(FIXTURE_DIR / "experiment_valid.yaml"),
            "num_episodes": 3,
        }
    ]
    raw["windows"] = {
        "input_steps": 2,
        "pred_steps": 2,
        "stride_steps": 2,
        "risk_label_horizons_s": [5, 10],
        "negative_positive_sampling": {
            "enabled": True,
            "max_negative_to_positive_ratio": 2,
        },
    }
    raw["split"]["holdout"] = {"unseen_layout": False, "unseen_num_cranes": False}
    path = tmp_path / "dataset.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def test_module_o_end_to_end_builds_queryable_dataset(tmp_path: Path) -> None:
    source_root = tmp_path / "runs"
    _episode(source_root, "E001", high=True)
    _episode(source_root, "E002")
    _episode(source_root, "E003", failed=True)
    output_root = tmp_path / "datasets"

    cli_result = build_dataset_from_config(
        _dataset_config_file(tmp_path),
        source_roots=[source_root],
        output_root=output_root,
        copy_mode="index_only",
        output_json=True,
    )

    assert cli_result.exit_code == 0, cli_result.stderr
    payload = json.loads(cli_result.stdout)
    dataset_dir = Path(payload["dataset_dir"])
    windows = pq.read_table(dataset_dir / "index" / "windows.parquet").to_pylist()
    assert windows
    DatasetWindowIndexRow.model_validate(windows[0])
    assert any(row["is_positive"] for row in windows)

    summary = json.loads((dataset_dir / "metadata" / "dataset_summary.json").read_text())
    assert summary["num_episodes"] == 2
    assert summary["num_quarantined"] == 1
    assert "risk_frame_ratio.high_min" in summary["target_gaps"]

    app = create_app()
    app.state.dataset_root = output_root
    client = TestClient(app)
    list_response = client.get("/datasets")
    summary_response = client.get(f"/datasets/{payload['dataset_id']}/summary")

    assert list_response.status_code == 200
    assert list_response.json()["data"]["items"][0]["summary_available"] is True
    assert summary_response.status_code == 200
    assert summary_response.json()["data"]["summary"]["num_quarantined"] == 1


def test_module_o_acceptance_reports_source_missing_error(tmp_path: Path) -> None:
    result = build_dataset_from_config(
        _dataset_config_file(tmp_path),
        source_roots=[tmp_path / "missing"],
        output_root=tmp_path / "datasets",
        output_json=True,
    )

    assert result.exit_code == 4
    assert "DATASET_E_SOURCE_NOT_FOUND" in result.stderr
