from __future__ import annotations

import json
import math
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from backend.app.schemas.training import (
    TRAINING_E_SOURCE_SCHEMA_INVALID,
    StgnnConversionResult,
    TrainingConversionError,
)
from backend.app.training.converter import StgnnDatasetConverter
from scripts.build_stgnn_dataset import main as main_build_stgnn_dataset


def test_converter_builds_index_manifest_and_summary_for_tiny_dataset(tmp_path: Path) -> None:
    dataset_root = _write_tiny_dataset(tmp_path)
    output_root = tmp_path / "stgnn-output"

    result = StgnnDatasetConverter().convert(
        dataset_root=dataset_root,
        output_root=output_root,
    )

    assert isinstance(result, StgnnConversionResult)
    assert len(result.samples) == 2
    assert result.summary.sample_counts == {"train": 1, "val": 1}
    assert (output_root / "metadata" / "stgnn_manifest.json").is_file()
    assert (output_root / "metadata" / "stgnn_summary.json").is_file()
    assert (output_root / "metadata" / "conversion_report.json").is_file()
    assert (output_root / "index" / "samples.parquet").is_file()
    rows = pq.read_table(output_root / "index" / "samples.parquet").to_pylist()
    assert rows[0]["metadata_json"]["episode_id"] == "E001"


def test_converter_split_filter_only_converts_requested_split(tmp_path: Path) -> None:
    dataset_root = _write_tiny_dataset(tmp_path)

    result = StgnnDatasetConverter().convert(
        dataset_root=dataset_root,
        output_root=tmp_path / "stgnn-output",
        splits=["train"],
    )

    assert [sample.split for sample in result.samples] == ["train"]
    assert result.summary.sample_counts == {"train": 1}


def test_converter_dry_run_validates_without_writing_outputs(tmp_path: Path) -> None:
    dataset_root = _write_tiny_dataset(tmp_path)
    output_root = tmp_path / "stgnn-output"

    result = StgnnDatasetConverter(dry_run=True).convert(
        dataset_root=dataset_root,
        output_root=output_root,
    )

    assert len(result.samples) == 2
    assert not output_root.exists()


def test_converter_strict_mode_fails_on_bad_episode_source(tmp_path: Path) -> None:
    dataset_root = _write_tiny_dataset(tmp_path, drop_trajectory_field="theta_sin")

    with pytest.raises(TrainingConversionError) as exc_info:
        StgnnDatasetConverter(strict=True).convert(
            dataset_root=dataset_root,
            output_root=tmp_path / "stgnn-output",
        )

    assert exc_info.value.code == TRAINING_E_SOURCE_SCHEMA_INVALID


def test_converter_lenient_mode_skips_bad_sample(tmp_path: Path) -> None:
    dataset_root = _write_tiny_dataset(tmp_path, drop_trajectory_field_for_episode="E002")

    result = StgnnDatasetConverter(strict=False).convert(
        dataset_root=dataset_root,
        output_root=tmp_path / "stgnn-output",
    )

    assert [sample.episode_id for sample in result.samples] == ["E001"]
    assert result.summary.skipped_counts == {"val": 1}
    assert result.summary.warnings
    assert "sk-" not in json.dumps(result.summary.model_dump(mode="json"))


def test_build_stgnn_dataset_cli_help_lists_expected_options(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main_build_stgnn_dataset(["--help"])

    output = capsys.readouterr().out
    assert exc_info.value.code == 0
    assert "--dataset-root" in output
    assert "--output-root" in output
    assert "--split" in output
    assert "--strict" in output
    assert "--dry-run" in output


def test_build_stgnn_dataset_cli_returns_nonzero_for_strict_failure(tmp_path: Path, capsys) -> None:
    dataset_root = _write_tiny_dataset(tmp_path, drop_trajectory_field="theta_sin")

    exit_code = main_build_stgnn_dataset(
        [
            "--dataset-root",
            str(dataset_root),
            "--output-root",
            str(tmp_path / "stgnn-output"),
            "--strict",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code != 0
    assert "TRAINING_E_SOURCE_SCHEMA_INVALID" in captured.err


def _write_tiny_dataset(
    tmp_path: Path,
    *,
    drop_trajectory_field: str | None = None,
    drop_trajectory_field_for_episode: str | None = None,
) -> Path:
    dataset_root = tmp_path / "dataset-a"
    metadata_dir = dataset_root / "metadata"
    index_dir = dataset_root / "index"
    metadata_dir.mkdir(parents=True)
    index_dir.mkdir(parents=True)

    windows = [
        _window_row("E001", "train", 0),
        _window_row("E002", "val", 0),
    ]
    _write_json(metadata_dir / "dataset_manifest.json", _dataset_manifest())
    _write_json(metadata_dir / "dataset_summary.json", _dataset_summary())
    _write_json(metadata_dir / "split_manifest.json", _split_manifest())
    pq.write_table(pa.Table.from_pylist(windows), index_dir / "windows.parquet")
    for episode_id in ["E001", "E002"]:
        drop = drop_trajectory_field
        if drop_trajectory_field_for_episode == episode_id:
            drop = "theta_sin"
        _write_episode(dataset_root, episode_id=episode_id, drop_trajectory_field=drop)
    return dataset_root


def _write_episode(
    dataset_root: Path,
    *,
    episode_id: str,
    drop_trajectory_field: str | None = None,
) -> None:
    data_dir = dataset_root / "episodes" / episode_id / "data"
    metadata_dir = dataset_root / "episodes" / episode_id / "metadata"
    visual_dir = dataset_root / "episodes" / episode_id / "visual"
    data_dir.mkdir(parents=True)
    metadata_dir.mkdir(parents=True)
    visual_dir.mkdir(parents=True)
    trajectory_rows = [
        _trajectory_row(episode_id, frame, crane)
        for frame in range(4)
        for crane in ["C1", "C2"]
    ]
    if drop_trajectory_field:
        for row in trajectory_rows:
            row.pop(drop_trajectory_field, None)
    pq.write_table(pa.Table.from_pylist(trajectory_rows), data_dir / "trajectories.parquet")
    pq.write_table(
        pa.Table.from_pylist([_pair_row(episode_id, frame) for frame in range(4)]),
        data_dir / "pair_risks.parquet",
    )
    pq.write_table(
        pa.Table.from_pylist([_graph_row(episode_id, frame) for frame in range(4)]),
        data_dir / "graph_edges.parquet",
    )
    pq.write_table(pa.Table.from_pylist([_task_row(episode_id)]), data_dir / "tasks.parquet")
    _write_json(metadata_dir / "episode_summary.json", {"episode_id": episode_id})
    _write_json(visual_dir / "episode_manifest.json", {"episode_id": episode_id})


def _dataset_manifest() -> dict:
    return {
        "schema_version": "1.0",
        "dataset_id": "dataset-a",
        "created_at": "2026-06-14T00:00:00Z",
        "git_commit": None,
        "source_roots": ["runs"],
        "copy_mode": "index_only",
        "split_strategy": "by_episode",
        "window_config": {"input_steps": 2, "pred_steps": 2, "stride_steps": 1},
        "config": {},
        "files": [],
        "warnings": [],
    }


def _dataset_summary() -> dict:
    return {
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


def _split_manifest() -> dict:
    return {
        "schema_version": "1.0",
        "dataset_id": "dataset-a",
        "split_strategy": "by_episode",
        "split_counts": {"train": 1, "val": 1},
        "assignments": [
            _assignment("E001", "train"),
            _assignment("E002", "val"),
        ],
    }


def _assignment(episode_id: str, split: str) -> dict:
    return {
        "schema_version": "1.0",
        "episode_id": episode_id,
        "split": split,
        "reason": split,
        "holdout_flags": {},
        "scenario_id": "scenario-a",
        "layout_hash": None,
        "num_cranes": 2,
    }


def _window_row(episode_id: str, split: str, start_frame: int) -> dict:
    return {
        "schema_version": "1.0",
        "dataset_id": "dataset-a",
        "split": split,
        "episode_id": episode_id,
        "scenario_id": "scenario-a",
        "start_frame": start_frame,
        "input_steps": 2,
        "pred_steps": 2,
        "stride_steps": 1,
        "input_start_time_s": 0.0,
        "prediction_end_time_s": 2.0,
        "num_cranes": 2,
        "label_horizons_s": [5.0],
        "source_paths": {
            "trajectories": f"episodes/{episode_id}/data/trajectories.parquet",
            "pair_risks": f"episodes/{episode_id}/data/pair_risks.parquet",
            "graph_edges": f"episodes/{episode_id}/data/graph_edges.parquet",
            "tasks": f"episodes/{episode_id}/data/tasks.parquet",
            "episode_summary": f"episodes/{episode_id}/metadata/episode_summary.json",
            "episode_manifest": f"episodes/{episode_id}/visual/episode_manifest.json",
        },
        "is_positive": False,
    }


def _trajectory_row(episode_id: str, frame: int, crane_id: str) -> dict:
    angle = frame * 0.1
    return {
        "schema_version": "1.0",
        "episode_id": episode_id,
        "scenario_id": "scenario-a",
        "frame": frame,
        "time_s": frame * 0.5,
        "crane_id": crane_id,
        "theta_rad": angle,
        "theta_sin": math.sin(angle),
        "theta_cos": math.cos(angle),
        "theta_dot_rad_s": 0.1,
        "theta_ddot_rad_s2": 0.0,
        "trolley_r_m": 20.0 + frame,
        "trolley_v_m_s": 0.5,
        "hook_h_m": 30.0,
        "hoist_v_m_s": 0.0,
        "root_x": 0.0,
        "root_y": 0.0,
        "root_z": 45.0,
        "tip_x": 40.0,
        "tip_y": 5.0,
        "tip_z": 45.0,
        "hook_x": 20.0 + frame,
        "hook_y": 2.0,
        "hook_z": 30.0,
        "load_attached": True,
        "load_weight_t": 1.0,
        "task_id": "T1",
        "task_stage": "move_to_pickup",
        "wind_speed_m_s": 4.0,
        "wind_gust_m_s": 6.0,
        "wind_direction_deg": 90.0,
        "visibility_level": "clear",
    }


def _pair_row(episode_id: str, frame: int) -> dict:
    return {
        "schema_version": "1.0",
        "episode_id": episode_id,
        "scenario_id": "scenario-a",
        "frame": frame,
        "time_s": frame * 0.5,
        "crane_i": "C1",
        "crane_j": "C2",
        "distance_min_raw_now_m": 6.0,
        "clearance_min_now_m": 4.0,
        "risk_level_now": "safe",
        "risk_level_5s": "safe",
        "collision_label_5s": 0,
        "min_clearance_future_5s_m": 2.0,
        "ttc_5s_s": None,
    }


def _graph_row(episode_id: str, frame: int) -> dict:
    return {
        "schema_version": "1.0",
        "episode_id": episode_id,
        "frame": frame,
        "time_s": frame * 0.5,
        "src_crane_id": "C1",
        "dst_crane_id": "C2",
        "edge_distance_m": 6.0,
        "edge_overlap_ratio": 0.5,
        "edge_delta_height_m": 0.0,
        "edge_delta_theta_rad": 0.1,
        "edge_delta_theta_dot_rad_s": 0.0,
        "edge_ttc_s": None,
        "edge_risk_level": "safe",
        "edge_weight_physics_prior": 0.5,
    }


def _task_row(episode_id: str) -> dict:
    return {
        "schema_version": "1.0",
        "episode_id": episode_id,
        "scenario_id": "scenario-a",
        "task_id": "T1",
        "crane_id": "C1",
        "task_type": "lift",
        "status": "active",
        "pickup_x": 0.0,
        "pickup_y": 0.0,
        "pickup_z": 0.0,
        "dropoff_x": 5.0,
        "dropoff_y": 5.0,
        "dropoff_z": 0.0,
        "pickup_zone_id": "pickup",
        "dropoff_zone_id": "dropoff",
        "load_type": "steel",
        "load_weight_t": 1.0,
        "load_size_x_m": 1.0,
        "load_size_y_m": 1.0,
        "load_size_z_m": 1.0,
        "deadline_missed": False,
        "overtime_s": 0.0,
    }


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
