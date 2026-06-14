from __future__ import annotations

import math

import numpy as np
import pyarrow as pa
import pytest

from backend.app.schemas.dataset import DatasetWindowIndexRow
from backend.app.schemas.training import (
    TRAINING_E_SOURCE_SCHEMA_INVALID,
    TRAINING_E_TIME_LEAKAGE,
    StgnnFeatureSpec,
    TrainingConversionError,
    default_stgnn_feature_spec,
)
from backend.app.training.episode_source import EpisodeTables
from backend.app.training.node_features import NodeFeatureBuilder


def test_node_feature_builder_outputs_input_window_tensor_and_mask() -> None:
    spec = default_stgnn_feature_spec(max_nodes=4, risk_label_horizons_s=[5.0])
    X_node, node_mask = NodeFeatureBuilder(feature_spec=spec).build(
        window=_window(),
        tables=_tables(),
        crane_order=["C1", "C2", "C3"],
        max_nodes=4,
    )

    assert X_node.shape == (2, 4, len(spec.node_features))
    assert node_mask.tolist() == [True, True, True, False]
    assert np.isfinite(X_node).all()
    assert X_node[0, 0, spec.node_features.index("theta_sin")] == pytest.approx(0.0)
    assert X_node[0, 0, spec.node_features.index("load_attached")] == 1.0
    assert X_node[0, 0, spec.node_features.index("has_task")] == 1.0
    assert X_node[0, 0, spec.node_features.index("wind_direction_sin")] == pytest.approx(1.0)
    assert X_node[0, 0, spec.node_features.index("wind_direction_cos")] == pytest.approx(0.0)
    assert X_node[1, 0, spec.node_features.index("hook_x")] != 9999.0
    assert not X_node[:, 3, :].any()


def test_node_feature_builder_uses_zero_defaults_for_nullable_optional_values() -> None:
    spec = default_stgnn_feature_spec(max_nodes=3, risk_label_horizons_s=[5.0])
    tables = _tables(load_weight_t=None, visibility_level=None, task_stage="unknown-stage")

    X_node, _ = NodeFeatureBuilder(feature_spec=spec).build(
        window=_window(),
        tables=tables,
        crane_order=["C1", "C2", "C3"],
        max_nodes=3,
    )

    assert X_node[0, 0, spec.node_features.index("load_weight_t")] == 0.0
    assert X_node[0, 0, spec.node_features.index("visibility_code")] == 0.0
    assert X_node[0, 0, spec.node_features.index("task_stage_code")] == 0.0


def test_node_feature_builder_rejects_future_label_feature_names() -> None:
    spec = StgnnFeatureSpec(
        node_features=["theta_sin", "collision_label_5s"],
        edge_features=["edge_distance_m"],
        traj_targets=["hook_x"],
        risk_targets=["collision_label"],
        risk_label_horizons_s=[5.0],
        max_nodes=3,
    )

    with pytest.raises(TrainingConversionError) as exc_info:
        NodeFeatureBuilder(feature_spec=spec).build(
            window=_window(),
            tables=_tables(),
            crane_order=["C1", "C2", "C3"],
            max_nodes=3,
        )

    assert exc_info.value.code == TRAINING_E_TIME_LEAKAGE


def test_node_feature_builder_rejects_missing_required_field() -> None:
    rows = [_trajectory_row(frame, crane) for frame in range(3) for crane in ["C1", "C2", "C3"]]
    for row in rows:
        row.pop("theta_sin")
    tables = _tables(rows=rows)

    with pytest.raises(TrainingConversionError) as exc_info:
        NodeFeatureBuilder(feature_spec=default_stgnn_feature_spec(max_nodes=3, risk_label_horizons_s=[5.0])).build(
            window=_window(),
            tables=tables,
            crane_order=["C1", "C2", "C3"],
            max_nodes=3,
        )

    assert exc_info.value.code == TRAINING_E_SOURCE_SCHEMA_INVALID
    assert "theta_sin" in exc_info.value.details["missing_fields"]


def test_node_feature_builder_rejects_missing_input_frame_crane() -> None:
    rows = [
        _trajectory_row(frame, crane)
        for frame in range(3)
        for crane in ["C1", "C2", "C3"]
        if not (frame == 1 and crane == "C3")
    ]
    tables = _tables(rows=rows)

    with pytest.raises(TrainingConversionError) as exc_info:
        NodeFeatureBuilder(feature_spec=default_stgnn_feature_spec(max_nodes=3, risk_label_horizons_s=[5.0])).build(
            window=_window(),
            tables=tables,
            crane_order=["C1", "C2", "C3"],
            max_nodes=3,
        )

    assert exc_info.value.code == TRAINING_E_SOURCE_SCHEMA_INVALID
    assert exc_info.value.details["frame"] == 1


def _window() -> DatasetWindowIndexRow:
    return DatasetWindowIndexRow(
        dataset_id="dataset-a",
        split="train",
        episode_id="E001",
        start_frame=0,
        input_steps=2,
        pred_steps=1,
        stride_steps=1,
        input_start_time_s=0.0,
        prediction_end_time_s=1.5,
        num_cranes=3,
        label_horizons_s=[5.0],
        source_paths={"trajectories": "trajectories.parquet"},
    )


def _tables(
    *,
    rows: list[dict] | None = None,
    load_weight_t: float | None = 2.5,
    visibility_level: str | None = "clear",
    task_stage: str = "move_to_pickup",
) -> EpisodeTables:
    trajectory_rows = rows or [
        _trajectory_row(
            frame,
            crane,
            load_weight_t=load_weight_t,
            visibility_level=visibility_level,
            task_stage=task_stage,
        )
        for frame in range(3)
        for crane in ["C1", "C2", "C3"]
    ]
    return EpisodeTables(
        episode_id="E001",
        scenario_id=None,
        trajectories=pa.Table.from_pylist(trajectory_rows),
        pair_risks=pa.Table.from_pylist([]),
        graph_edges=None,
        tasks=None,
        episode_summary={"episode_id": "E001"},
        episode_manifest={"episode_id": "E001"},
        source_paths={},
    )


def _trajectory_row(
    frame: int,
    crane_id: str,
    *,
    load_weight_t: float | None = 2.5,
    visibility_level: str | None = "clear",
    task_stage: str = "move_to_pickup",
) -> dict:
    angle = frame * 0.1
    return {
        "schema_version": "1.0",
        "episode_id": "E001",
        "frame": frame,
        "time_s": frame * 0.5,
        "crane_id": crane_id,
        "theta_sin": math.sin(angle),
        "theta_cos": math.cos(angle),
        "theta_dot_rad_s": 0.1,
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
        "hook_x": 9999.0 if frame >= 2 else 20.0 + frame,
        "hook_y": 2.0,
        "hook_z": 30.0,
        "load_attached": True,
        "load_weight_t": load_weight_t,
        "task_id": "T1",
        "task_stage": task_stage,
        "wind_speed_m_s": 4.0,
        "wind_gust_m_s": 6.0,
        "wind_direction_deg": 90.0,
        "visibility_level": visibility_level,
    }
