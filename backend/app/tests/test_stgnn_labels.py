from __future__ import annotations

import math

import numpy as np
import pyarrow as pa
import pytest

from backend.app.schemas.dataset import DatasetWindowIndexRow
from backend.app.schemas.training import (
    TRAINING_E_LABEL_MISSING,
    TRAINING_E_SOURCE_SCHEMA_INVALID,
    TRAINING_E_TIME_AXIS_INVALID,
    StgnnFeatureSpec,
    TrainingConversionError,
    default_stgnn_feature_spec,
)
from backend.app.training.episode_source import EpisodeTables
from backend.app.training.labels import LabelBuilder, RISK_LEVEL_LABEL_CODES


def test_label_builder_outputs_prediction_trajectory_targets() -> None:
    spec = default_stgnn_feature_spec(max_nodes=4, risk_label_horizons_s=[5.0, 10.0, 15.0])
    Y_traj = LabelBuilder(feature_spec=spec).build_traj(
        window=_window(),
        tables=_tables(),
        crane_order=["C1", "C2", "C3"],
        max_nodes=4,
    )

    assert Y_traj.shape == (2, 4, len(spec.traj_targets))
    assert np.isfinite(Y_traj).all()
    assert Y_traj[0, 0, spec.traj_targets.index("hook_x")] == pytest.approx(22.0)
    assert Y_traj[1, 0, spec.traj_targets.index("hook_x")] == pytest.approx(23.0)
    assert not Y_traj[:, 3, :].any()


def test_label_builder_outputs_anchor_frame_risk_labels_and_mask() -> None:
    spec = default_stgnn_feature_spec(max_nodes=4, risk_label_horizons_s=[5.0, 10.0, 15.0])
    Y_risk, risk_mask = LabelBuilder(feature_spec=spec).build_risk(
        window=_window(),
        tables=_tables(),
        crane_order=["C1", "C2", "C3"],
        max_nodes=4,
    )

    risk_level_index = spec.risk_targets.index("risk_level_code")
    collision_index = spec.risk_targets.index("collision_label")
    clearance_index = spec.risk_targets.index("min_clearance_future_m")
    ttc_index = spec.risk_targets.index("ttc_s")
    assert Y_risk.shape == (3, 4, 4, len(spec.risk_targets))
    assert risk_mask.shape == (3, 4, 4)
    assert risk_mask[0, 0, 1]
    assert risk_mask[0, 1, 0]
    assert not risk_mask[0, 0, 0]
    assert Y_risk[0, 0, 1, risk_level_index] == RISK_LEVEL_LABEL_CODES["high"]
    assert Y_risk[1, 0, 1, collision_index] == 1.0
    assert Y_risk[2, 0, 1, clearance_index] == pytest.approx(1.5)
    assert Y_risk[0, 0, 1, ttc_index] == -1.0
    assert Y_risk[0, 0, 1, :] == pytest.approx(Y_risk[0, 1, 0, :])


def test_label_builder_single_crane_has_empty_risk_mask() -> None:
    spec = default_stgnn_feature_spec(max_nodes=3, risk_label_horizons_s=[5.0])
    Y_risk, risk_mask = LabelBuilder(feature_spec=spec).build_risk(
        window=_window(num_cranes=1),
        tables=_tables(cranes=["C1"], pair_rows=[]),
        crane_order=["C1"],
        max_nodes=3,
    )

    assert Y_risk.shape == (1, 3, 3, len(spec.risk_targets))
    assert not Y_risk.any()
    assert not risk_mask.any()


def test_label_builder_missing_pair_at_anchor_leaves_mask_false() -> None:
    spec = default_stgnn_feature_spec(max_nodes=3, risk_label_horizons_s=[5.0])
    Y_risk, risk_mask = LabelBuilder(feature_spec=spec).build_risk(
        window=_window(),
        tables=_tables(pair_rows=[_pair_row(frame=0, i="C1", j="C2")]),
        crane_order=["C1", "C2", "C3"],
        max_nodes=3,
    )

    assert not risk_mask.any()
    assert not Y_risk.any()


def test_label_builder_rejects_missing_prediction_frame_crane() -> None:
    rows = [
        _trajectory_row(frame, crane)
        for frame in range(5)
        for crane in ["C1", "C2", "C3"]
        if not (frame == 2 and crane == "C3")
    ]
    with pytest.raises(TrainingConversionError) as exc_info:
        LabelBuilder(feature_spec=default_stgnn_feature_spec(max_nodes=3, risk_label_horizons_s=[5.0])).build_traj(
            window=_window(),
            tables=_tables(trajectory_rows=rows),
            crane_order=["C1", "C2", "C3"],
            max_nodes=3,
        )

    assert exc_info.value.code == TRAINING_E_TIME_AXIS_INVALID
    assert exc_info.value.details["frame"] == 2


def test_label_builder_rejects_missing_horizon_columns() -> None:
    pair_rows = [_pair_row(frame=1, i="C1", j="C2")]
    for row in pair_rows:
        row.pop("risk_level_10s")

    with pytest.raises(TrainingConversionError) as exc_info:
        LabelBuilder(feature_spec=default_stgnn_feature_spec(max_nodes=3, risk_label_horizons_s=[10.0])).build_risk(
            window=_window(),
            tables=_tables(pair_rows=pair_rows),
            crane_order=["C1", "C2", "C3"],
            max_nodes=3,
        )

    assert exc_info.value.code == TRAINING_E_LABEL_MISSING
    assert "risk_level_10s" in exc_info.value.details["missing_fields"]


def test_label_builder_rejects_invalid_collision_label() -> None:
    pair_rows = [_pair_row(frame=1, i="C1", j="C2", collision_5s=2)]

    with pytest.raises(TrainingConversionError) as exc_info:
        LabelBuilder(feature_spec=default_stgnn_feature_spec(max_nodes=3, risk_label_horizons_s=[5.0])).build_risk(
            window=_window(),
            tables=_tables(pair_rows=pair_rows),
            crane_order=["C1", "C2", "C3"],
            max_nodes=3,
        )

    assert exc_info.value.code == TRAINING_E_SOURCE_SCHEMA_INVALID
    assert exc_info.value.details["field"] == "collision_label_5s"


def test_label_builder_rejects_risk_level_now_as_target() -> None:
    spec = StgnnFeatureSpec(
        node_features=["theta_sin"],
        edge_features=["edge_distance_m"],
        traj_targets=["hook_x"],
        risk_targets=["risk_level_now"],
        risk_label_horizons_s=[5.0],
        max_nodes=3,
    )

    with pytest.raises(TrainingConversionError) as exc_info:
        LabelBuilder(feature_spec=spec).build_risk(
            window=_window(),
            tables=_tables(),
            crane_order=["C1", "C2", "C3"],
            max_nodes=3,
        )

    assert exc_info.value.code == TRAINING_E_LABEL_MISSING


def _window(*, num_cranes: int = 3) -> DatasetWindowIndexRow:
    return DatasetWindowIndexRow(
        dataset_id="dataset-a",
        split="train",
        episode_id="E001",
        start_frame=0,
        input_steps=2,
        pred_steps=2,
        stride_steps=1,
        input_start_time_s=0.0,
        prediction_end_time_s=2.0,
        num_cranes=num_cranes,
        label_horizons_s=[5.0, 10.0, 15.0],
        source_paths={"trajectories": "trajectories.parquet"},
    )


def _tables(
    *,
    cranes: list[str] | None = None,
    trajectory_rows: list[dict] | None = None,
    pair_rows: list[dict] | None = None,
) -> EpisodeTables:
    cranes = cranes or ["C1", "C2", "C3"]
    trajectory_rows = trajectory_rows or [
        _trajectory_row(frame, crane)
        for frame in range(5)
        for crane in cranes
    ]
    pair_rows = pair_rows if pair_rows is not None else [
        _pair_row(frame=1, i="C1", j="C2"),
        _pair_row(frame=2, i="C1", j="C2", risk_5s="safe"),
    ]
    return EpisodeTables(
        episode_id="E001",
        scenario_id=None,
        trajectories=pa.Table.from_pylist(trajectory_rows),
        pair_risks=pa.Table.from_pylist(pair_rows),
        graph_edges=None,
        tasks=None,
        episode_summary={"episode_id": "E001"},
        episode_manifest={"episode_id": "E001"},
        source_paths={},
    )


def _trajectory_row(frame: int, crane_id: str) -> dict:
    angle = frame * 0.1
    return {
        "schema_version": "1.0",
        "episode_id": "E001",
        "frame": frame,
        "time_s": frame * 0.5,
        "crane_id": crane_id,
        "theta_sin": math.sin(angle),
        "theta_cos": math.cos(angle),
        "trolley_r_m": 20.0 + frame,
        "hook_h_m": 30.0,
        "hook_x": 20.0 + frame if frame < 4 else 9999.0,
        "hook_y": 2.0,
        "hook_z": 30.0,
    }


def _pair_row(
    *,
    frame: int,
    i: str,
    j: str,
    risk_5s: str = "high",
    collision_5s: int = 0,
) -> dict:
    return {
        "schema_version": "1.0",
        "episode_id": "E001",
        "frame": frame,
        "time_s": frame * 0.5,
        "crane_i": i,
        "crane_j": j,
        "risk_level_now": "safe",
        "risk_level_5s": risk_5s,
        "collision_label_5s": collision_5s,
        "min_clearance_future_5s_m": 2.5,
        "ttc_5s_s": None,
        "risk_level_10s": "collision",
        "collision_label_10s": 1,
        "min_clearance_future_10s_m": -0.5,
        "ttc_10s_s": 3.0,
        "risk_level_15s": "medium",
        "collision_label_15s": 0,
        "min_clearance_future_15s_m": 1.5,
        "ttc_15s_s": 5.0,
    }
