from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from backend.app.schemas.dataset import DatasetWindowIndexRow
from backend.app.schemas.training import (
    TRAINING_E_LABEL_MISSING,
    TRAINING_E_SOURCE_MISSING,
    TRAINING_E_SOURCE_SCHEMA_INVALID,
    TRAINING_E_TIME_AXIS_INVALID,
    TrainingConversionError,
)
from backend.app.training.episode_source import EpisodeParquetSource, EpisodeTables


def test_episode_source_loads_valid_tiny_episode(tmp_path: Path) -> None:
    dataset_root = _write_episode_fixture(tmp_path)
    window = _window()

    tables = EpisodeParquetSource(dataset_root=dataset_root).load_for_window(window)

    assert isinstance(tables, EpisodeTables)
    assert tables.episode_id == "E001"
    assert tables.scenario_id == "scenario-a"
    assert tables.trajectories.num_rows == 12
    assert tables.pair_risks.num_rows == 4
    assert tables.graph_edges is not None
    assert tables.tasks is not None
    assert tables.episode_summary["episode_id"] == "E001"
    assert "trajectories" in tables.source_paths


def test_episode_source_allows_single_crane_without_pair_risks(tmp_path: Path) -> None:
    dataset_root = _write_episode_fixture(
        tmp_path,
        cranes=["C1"],
        pair_rows=[],
        graph_rows=[],
    )
    window = _window(num_cranes=1)

    tables = EpisodeParquetSource(
        dataset_root=dataset_root,
        allow_graph_edge_fallback=True,
    ).load_for_window(window)

    assert tables.pair_risks.num_rows == 0
    assert tables.graph_edges is None


def test_episode_source_rejects_missing_trajectory_field(tmp_path: Path) -> None:
    dataset_root = _write_episode_fixture(tmp_path, drop_trajectory_field="hook_x")

    with pytest.raises(TrainingConversionError) as exc_info:
        EpisodeParquetSource(dataset_root=dataset_root).load_for_window(_window())

    assert exc_info.value.code == TRAINING_E_SOURCE_SCHEMA_INVALID
    assert "hook_x" in exc_info.value.details["missing_fields"]


def test_episode_source_rejects_incomplete_crane_set_by_frame(tmp_path: Path) -> None:
    dataset_root = _write_episode_fixture(tmp_path, omit_trajectory_row=(1, "C3"))

    with pytest.raises(TrainingConversionError) as exc_info:
        EpisodeParquetSource(dataset_root=dataset_root).load_for_window(_window())

    assert exc_info.value.code == TRAINING_E_TIME_AXIS_INVALID
    assert exc_info.value.details["frame"] == 1


def test_episode_source_rejects_non_monotonic_time(tmp_path: Path) -> None:
    dataset_root = _write_episode_fixture(tmp_path, time_by_frame={2: 0.25})

    with pytest.raises(TrainingConversionError) as exc_info:
        EpisodeParquetSource(dataset_root=dataset_root).load_for_window(_window())

    assert exc_info.value.code == TRAINING_E_TIME_AXIS_INVALID
    assert exc_info.value.details["frame"] == 2


def test_episode_source_rejects_window_beyond_trajectory(tmp_path: Path) -> None:
    dataset_root = _write_episode_fixture(tmp_path, frame_count=3)

    with pytest.raises(TrainingConversionError) as exc_info:
        EpisodeParquetSource(dataset_root=dataset_root).load_for_window(_window())

    assert exc_info.value.code == TRAINING_E_TIME_AXIS_INVALID


def test_episode_source_rejects_missing_horizon_label(tmp_path: Path) -> None:
    dataset_root = _write_episode_fixture(tmp_path, drop_pair_field="collision_label_10s")

    with pytest.raises(TrainingConversionError) as exc_info:
        EpisodeParquetSource(dataset_root=dataset_root).load_for_window(_window())

    assert exc_info.value.code == TRAINING_E_LABEL_MISSING
    assert "collision_label_10s" in exc_info.value.details["missing_fields"]


def test_episode_source_rejects_episode_id_mismatch(tmp_path: Path) -> None:
    dataset_root = _write_episode_fixture(tmp_path, trajectory_episode_id="OTHER")

    with pytest.raises(TrainingConversionError) as exc_info:
        EpisodeParquetSource(dataset_root=dataset_root).load_for_window(_window())

    assert exc_info.value.code == TRAINING_E_SOURCE_SCHEMA_INVALID
    assert exc_info.value.details["expected"] == "E001"


def test_episode_source_requires_graph_edges_without_fallback(tmp_path: Path) -> None:
    dataset_root = _write_episode_fixture(tmp_path, graph_rows=[])

    with pytest.raises(TrainingConversionError) as exc_info:
        EpisodeParquetSource(dataset_root=dataset_root).load_for_window(_window())

    assert exc_info.value.code == TRAINING_E_SOURCE_MISSING
    assert "graph_edges" in exc_info.value.details["role"]


def _write_episode_fixture(
    tmp_path: Path,
    *,
    cranes: list[str] | None = None,
    frame_count: int = 4,
    pair_rows: list[dict[str, Any]] | None = None,
    graph_rows: list[dict[str, Any]] | None = None,
    drop_trajectory_field: str | None = None,
    drop_pair_field: str | None = None,
    omit_trajectory_row: tuple[int, str] | None = None,
    time_by_frame: dict[int, float] | None = None,
    trajectory_episode_id: str = "E001",
) -> Path:
    dataset_root = tmp_path / "dataset-a"
    episode_dir = dataset_root / "episodes" / "E001"
    data_dir = episode_dir / "data"
    metadata_dir = episode_dir / "metadata"
    visual_dir = episode_dir / "visual"
    data_dir.mkdir(parents=True)
    metadata_dir.mkdir(parents=True)
    visual_dir.mkdir(parents=True)

    cranes = cranes or ["C1", "C2", "C3"]
    trajectory_rows = []
    for frame in range(frame_count):
        for crane_id in cranes:
            if omit_trajectory_row == (frame, crane_id):
                continue
            row = _trajectory_row(
                episode_id=trajectory_episode_id,
                frame=frame,
                time_s=(time_by_frame or {}).get(frame, frame * 0.5),
                crane_id=crane_id,
            )
            if drop_trajectory_field:
                row.pop(drop_trajectory_field)
            trajectory_rows.append(row)

    if pair_rows is None:
        pair_rows = [_pair_row(frame=1), _pair_row(frame=2), _pair_row(frame=3), _pair_row(frame=0)]
    if drop_pair_field:
        pair_rows = [dict(row) for row in pair_rows]
        for row in pair_rows:
            row.pop(drop_pair_field, None)

    if graph_rows is None:
        graph_rows = [
            _graph_row(frame=frame, src="C1", dst="C2")
            for frame in range(frame_count)
        ]

    _write_parquet(data_dir / "trajectories.parquet", trajectory_rows)
    _write_parquet(data_dir / "pair_risks.parquet", pair_rows)
    if graph_rows:
        _write_parquet(data_dir / "graph_edges.parquet", graph_rows)
    _write_parquet(data_dir / "tasks.parquet", [_task_row()])
    _write_json(metadata_dir / "episode_summary.json", _episode_summary(num_cranes=len(cranes)))
    _write_json(visual_dir / "episode_manifest.json", _episode_manifest(num_cranes=len(cranes)))
    return dataset_root


def _window(*, num_cranes: int = 3) -> DatasetWindowIndexRow:
    return DatasetWindowIndexRow(
        dataset_id="dataset-a",
        split="train",
        episode_id="E001",
        scenario_id="scenario-a",
        start_frame=0,
        input_steps=2,
        pred_steps=2,
        stride_steps=1,
        input_start_time_s=0.0,
        prediction_end_time_s=2.0,
        num_cranes=num_cranes,
        label_horizons_s=[5.0, 10.0],
        source_paths={
            "trajectories": "episodes/E001/data/trajectories.parquet",
            "pair_risks": "episodes/E001/data/pair_risks.parquet",
            "graph_edges": "episodes/E001/data/graph_edges.parquet",
            "tasks": "episodes/E001/data/tasks.parquet",
            "episode_summary": "episodes/E001/metadata/episode_summary.json",
            "episode_manifest": "episodes/E001/visual/episode_manifest.json",
        },
    )


def _trajectory_row(
    *,
    episode_id: str,
    frame: int,
    time_s: float,
    crane_id: str,
) -> dict[str, Any]:
    angle = frame * 0.1
    return {
        "schema_version": "1.0",
        "episode_id": episode_id,
        "scenario_id": "scenario-a",
        "frame": frame,
        "time_s": time_s,
        "crane_id": crane_id,
        "theta_rad": angle,
        "theta_sin": math.sin(angle),
        "theta_cos": math.cos(angle),
        "theta_dot_rad_s": 0.01,
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
        "hook_x": 20.0,
        "hook_y": 2.0,
        "hook_z": 30.0,
        "load_attached": False,
        "load_weight_t": None,
        "task_id": "T1",
        "task_stage": "move_to_pickup",
        "wind_speed_m_s": 4.0,
        "wind_gust_m_s": 6.0,
        "wind_direction_deg": 90.0,
        "visibility_level": "clear",
    }


def _pair_row(*, frame: int) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "episode_id": "E001",
        "scenario_id": "scenario-a",
        "frame": frame,
        "time_s": frame * 0.5,
        "crane_i": "C1",
        "crane_j": "C2",
        "distance_min_raw_now_m": 10.0,
        "clearance_min_now_m": 8.0,
        "risk_level_now": "safe",
        "min_clearance_future_5s_m": 7.0,
        "min_clearance_future_10s_m": 6.0,
        "ttc_5s_s": None,
        "ttc_10s_s": None,
        "risk_level_5s": "safe",
        "risk_level_10s": "safe",
        "collision_label_5s": 0,
        "collision_label_10s": 0,
    }


def _graph_row(*, frame: int, src: str, dst: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "episode_id": "E001",
        "frame": frame,
        "time_s": frame * 0.5,
        "src_crane_id": src,
        "dst_crane_id": dst,
        "edge_distance_m": 10.0,
        "edge_overlap_ratio": 0.5,
        "edge_delta_height_m": 0.0,
        "edge_delta_theta_rad": 0.1,
        "edge_delta_theta_dot_rad_s": 0.0,
        "edge_ttc_s": None,
        "edge_risk_level": "safe",
        "edge_weight_physics_prior": 0.5,
    }


def _task_row() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "episode_id": "E001",
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


def _episode_summary(*, num_cranes: int) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "episode_id": "E001",
        "scenario_id": "scenario-a",
        "episode_status": "completed",
        "duration_s": 2.0,
        "num_cranes": num_cranes,
    }


def _episode_manifest(*, num_cranes: int) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "episode_id": "E001",
        "scenario_id": "scenario-a",
        "episode_status": "completed",
        "frame_count": 4,
        "dt": 0.5,
        "cranes": [{"crane_id": f"C{index + 1}"} for index in range(num_cranes)],
    }


def _write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    pq.write_table(pa.Table.from_pylist(rows), path)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
