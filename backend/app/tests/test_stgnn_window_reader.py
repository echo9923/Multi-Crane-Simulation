from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from backend.app.schemas.dataset import DatasetWindowIndexRow
from backend.app.schemas.training import (
    TRAINING_E_MANIFEST_INVALID,
    TRAINING_E_SECRET_LEAKAGE,
    TRAINING_E_SPLIT_LEAKAGE,
    TRAINING_E_WINDOWS_INVALID,
    TrainingConversionError,
)
from backend.app.training.window_reader import DatasetWindowBundle, DatasetWindowReader


def test_window_reader_loads_and_sorts_module_o_dataset(tmp_path: Path) -> None:
    dataset_root = _write_dataset_root(
        tmp_path,
        windows=[
            _window_row(split="val", episode_id="E002", start_frame=4),
            _window_row(split="train", episode_id="E001", start_frame=8),
            _window_row(split="train", episode_id="E001", start_frame=0),
        ],
        assignments=[
            _assignment("E001", "train"),
            _assignment("E002", "val"),
        ],
    )

    bundle = DatasetWindowReader().read(dataset_root)

    assert isinstance(bundle, DatasetWindowBundle)
    assert bundle.dataset_id == "dataset-a"
    assert bundle.dataset_root == dataset_root
    assert bundle.split_assignments == {"E001": "train", "E002": "val"}
    assert [row.split for row in bundle.windows] == ["train", "train", "val"]
    assert [row.start_frame for row in bundle.windows] == [0, 8, 4]
    assert all(isinstance(row, DatasetWindowIndexRow) for row in bundle.windows)


def test_window_reader_rejects_duplicate_split_manifest_assignments(tmp_path: Path) -> None:
    dataset_root = _write_dataset_root(
        tmp_path,
        windows=[_window_row(split="train", episode_id="E001")],
        assignments=[
            _assignment("E001", "train"),
            _assignment("E001", "val"),
        ],
    )

    with pytest.raises(TrainingConversionError) as exc_info:
        DatasetWindowReader().read(dataset_root)

    assert exc_info.value.code == TRAINING_E_SPLIT_LEAKAGE
    assert exc_info.value.details["episode_id"] == "E001"


def test_window_reader_rejects_window_split_mismatch(tmp_path: Path) -> None:
    dataset_root = _write_dataset_root(
        tmp_path,
        windows=[_window_row(split="val", episode_id="E001")],
        assignments=[_assignment("E001", "train")],
    )

    with pytest.raises(TrainingConversionError) as exc_info:
        DatasetWindowReader().read(dataset_root)

    assert exc_info.value.code == TRAINING_E_SPLIT_LEAKAGE
    assert exc_info.value.details["expected"] == "train"
    assert exc_info.value.details["actual"] == "val"


def test_window_reader_rejects_episode_windows_across_splits(tmp_path: Path) -> None:
    dataset_root = _write_dataset_root(
        tmp_path,
        windows=[
            _window_row(split="train", episode_id="E001", start_frame=0),
            _window_row(split="val", episode_id="E001", start_frame=4),
        ],
        assignments=[],
    )

    with pytest.raises(TrainingConversionError) as exc_info:
        DatasetWindowReader().read(dataset_root)

    assert exc_info.value.code == TRAINING_E_SPLIT_LEAKAGE
    assert exc_info.value.details["episode_id"] == "E001"


def test_window_reader_rejects_dataset_id_mismatch(tmp_path: Path) -> None:
    dataset_root = _write_dataset_root(
        tmp_path,
        windows=[_window_row(dataset_id="other-dataset")],
        assignments=[_assignment("E001", "train")],
    )

    with pytest.raises(TrainingConversionError) as exc_info:
        DatasetWindowReader().read(dataset_root)

    assert exc_info.value.code == TRAINING_E_WINDOWS_INVALID
    assert exc_info.value.details["expected"] == "dataset-a"


def test_window_reader_rejects_missing_windows_parquet(tmp_path: Path) -> None:
    dataset_root = _write_dataset_root(
        tmp_path,
        windows=[_window_row()],
        assignments=[_assignment("E001", "train")],
    )
    (dataset_root / "index" / "windows.parquet").unlink()

    with pytest.raises(TrainingConversionError) as exc_info:
        DatasetWindowReader().read(dataset_root)

    assert exc_info.value.code == TRAINING_E_WINDOWS_INVALID
    assert "windows.parquet" in exc_info.value.details["path"]


def test_window_reader_rejects_secret_like_manifest_payload(tmp_path: Path) -> None:
    dataset_root = _write_dataset_root(
        tmp_path,
        windows=[_window_row()],
        assignments=[_assignment("E001", "train")],
        manifest_extra={"authorization": "Bearer sk-secret"},
    )

    with pytest.raises(TrainingConversionError) as exc_info:
        DatasetWindowReader().read(dataset_root)

    assert exc_info.value.code == TRAINING_E_SECRET_LEAKAGE
    assert "authorization" in exc_info.value.details["field_path"]


def test_window_reader_rejects_manifest_dataset_id_mismatch(tmp_path: Path) -> None:
    dataset_root = _write_dataset_root(
        tmp_path,
        windows=[_window_row()],
        assignments=[_assignment("E001", "train")],
    )
    manifest_path = dataset_root / "metadata" / "dataset_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["dataset_id"] = "wrong"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(TrainingConversionError) as exc_info:
        DatasetWindowReader().read(dataset_root)

    assert exc_info.value.code == TRAINING_E_MANIFEST_INVALID


def _write_dataset_root(
    tmp_path: Path,
    *,
    windows: list[dict[str, Any]],
    assignments: list[dict[str, Any]],
    manifest_extra: dict[str, Any] | None = None,
) -> Path:
    dataset_root = tmp_path / "dataset-a"
    metadata_dir = dataset_root / "metadata"
    index_dir = dataset_root / "index"
    metadata_dir.mkdir(parents=True)
    index_dir.mkdir(parents=True)

    manifest = {
        "schema_version": "1.0",
        "dataset_id": "dataset-a",
        "created_at": "2026-06-14T00:00:00Z",
        "git_commit": None,
        "source_roots": ["runs"],
        "copy_mode": "index_only",
        "split_strategy": "by_episode",
        "window_config": {
            "input_steps": 4,
            "pred_steps": 2,
            "stride_steps": 1,
            "risk_label_horizons_s": [5.0, 10.0],
        },
        "config": {},
        "files": [],
        "warnings": [],
    }
    if manifest_extra:
        manifest.update(manifest_extra)
    summary = {
        "schema_version": "1.0",
        "dataset_id": "dataset-a",
        "created_at": "2026-06-14T00:00:00Z",
        "git_commit": None,
        "num_episodes": 2,
        "num_quarantined": 0,
        "split_counts": {"train": 1, "val": 1},
        "window_counts": {"train": 1, "val": 1},
        "risk_distribution": {"safe": 1.0},
        "task_completion_rate": None,
        "near_miss_count": 0,
        "collision_count": 0,
        "warnings": [],
    }
    split_manifest = {
        "schema_version": "1.0",
        "dataset_id": "dataset-a",
        "split_strategy": "by_episode",
        "split_counts": {"train": 1, "val": 1},
        "assignments": assignments,
    }

    _write_json(metadata_dir / "dataset_manifest.json", manifest)
    _write_json(metadata_dir / "dataset_summary.json", summary)
    _write_json(metadata_dir / "split_manifest.json", split_manifest)
    pq.write_table(pa.Table.from_pylist(windows), index_dir / "windows.parquet")
    return dataset_root


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _assignment(episode_id: str, split: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "episode_id": episode_id,
        "split": split,
        "reason": f"{split} fixture",
        "holdout_flags": {},
        "scenario_id": None,
        "layout_hash": None,
        "num_cranes": 2,
    }


def _window_row(
    *,
    dataset_id: str = "dataset-a",
    split: str = "train",
    episode_id: str = "E001",
    start_frame: int = 0,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "dataset_id": dataset_id,
        "split": split,
        "episode_id": episode_id,
        "scenario_id": None,
        "start_frame": start_frame,
        "input_steps": 4,
        "pred_steps": 2,
        "stride_steps": 1,
        "input_start_time_s": float(start_frame),
        "prediction_end_time_s": float(start_frame + 6),
        "num_cranes": 2,
        "label_horizons_s": [5.0, 10.0],
        "source_paths": {"trajectories": f"episodes/{episode_id}/data/trajectories.parquet"},
        "is_positive": False,
    }
