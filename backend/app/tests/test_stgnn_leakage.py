from __future__ import annotations

import pytest

from backend.app.schemas.dataset import DatasetWindowIndexRow
from backend.app.schemas.training import (
    TRAINING_E_SOURCE_SCHEMA_INVALID,
    TRAINING_E_TIME_AXIS_INVALID,
    TRAINING_E_TIME_LEAKAGE,
    StgnnSampleMetadata,
    TrainingConversionError,
)
from backend.app.training.leakage import LeakageGuard


def test_leakage_guard_accepts_valid_input_and_label_ranges() -> None:
    LeakageGuard().validate_window_ranges(
        start_frame=10,
        input_steps=3,
        pred_steps=2,
        requested_input_frames=[10, 11, 12],
        requested_label_frames=[13, 14],
    )


def test_leakage_guard_rejects_future_label_feature_names() -> None:
    guard = LeakageGuard()

    for name in [
        "min_clearance_future_5s_m",
        "collision_label_10s",
        "risk_level_5s",
        "ttc_10s_s",
        "Future_Truth_Debug",
        "offline_label",
    ]:
        with pytest.raises(TrainingConversionError) as exc_info:
            guard.validate_feature_names(["theta_sin", name], kind="node")
        assert exc_info.value.code == TRAINING_E_TIME_LEAKAGE
        assert exc_info.value.details["field_name"] == name


def test_leakage_guard_rejects_input_frame_inside_prediction_window() -> None:
    with pytest.raises(TrainingConversionError) as exc_info:
        LeakageGuard().validate_window_ranges(
            start_frame=10,
            input_steps=3,
            pred_steps=2,
            requested_input_frames=[10, 11, 12, 13],
            requested_label_frames=[13, 14],
        )

    assert exc_info.value.code == TRAINING_E_TIME_LEAKAGE
    assert exc_info.value.details["frame"] == 13


def test_leakage_guard_rejects_label_frame_outside_prediction_window() -> None:
    with pytest.raises(TrainingConversionError) as exc_info:
        LeakageGuard().validate_window_ranges(
            start_frame=10,
            input_steps=3,
            pred_steps=2,
            requested_input_frames=[10, 11, 12],
            requested_label_frames=[13, 15],
        )

    assert exc_info.value.code == TRAINING_E_TIME_AXIS_INVALID
    assert exc_info.value.details["expected_frames"] == [13, 14]


def test_leakage_guard_validates_risk_anchor_frame() -> None:
    guard = LeakageGuard()
    guard.validate_risk_anchor_frame(
        start_frame=10,
        input_steps=3,
        anchor_frame=12,
    )

    with pytest.raises(TrainingConversionError) as exc_info:
        guard.validate_risk_anchor_frame(
            start_frame=10,
            input_steps=3,
            anchor_frame=13,
        )

    assert exc_info.value.code == TRAINING_E_TIME_LEAKAGE
    assert exc_info.value.details["expected_anchor_frame"] == 12


def test_leakage_guard_rejects_metadata_window_mismatch() -> None:
    window = _window()
    metadata = _metadata(split="val")

    with pytest.raises(TrainingConversionError) as exc_info:
        LeakageGuard().validate_sample_metadata(window=window, metadata=metadata)

    assert exc_info.value.code == TRAINING_E_SOURCE_SCHEMA_INVALID
    assert exc_info.value.details["field"] == "split"


def test_leakage_guard_accepts_metadata_matching_window() -> None:
    LeakageGuard().validate_sample_metadata(window=_window(), metadata=_metadata())


def _window() -> DatasetWindowIndexRow:
    return DatasetWindowIndexRow(
        dataset_id="dataset-a",
        split="train",
        scenario_id="scenario-a",
        episode_id="E001",
        start_frame=10,
        input_steps=3,
        pred_steps=2,
        stride_steps=1,
        input_start_time_s=5.0,
        prediction_end_time_s=7.0,
        num_cranes=2,
        label_horizons_s=[5.0, 10.0],
        source_paths={"trajectories": "trajectories.parquet"},
    )


def _metadata(*, split: str = "train") -> StgnnSampleMetadata:
    return StgnnSampleMetadata(
        dataset_id="dataset-a",
        split=split,
        scenario_id="scenario-a",
        episode_id="E001",
        start_frame=10,
        input_steps=3,
        pred_steps=2,
        stride_steps=1,
        risk_label_horizons_s=[5.0, 10.0],
        source_paths={"trajectories": "trajectories.parquet"},
        source_window_index={"row": 0},
        feature_spec_hash="a" * 64,
    )
