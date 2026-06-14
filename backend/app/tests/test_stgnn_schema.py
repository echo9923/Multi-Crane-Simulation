from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from backend.app.schemas.training import (
    TRAINING_E_CONFIG_INVALID,
    TRAINING_E_SECRET_LEAKAGE,
    TRAINING_SCHEMA_VERSION,
    StgnnConversionOptions,
    StgnnConversionSummary,
    StgnnFeatureSpec,
    StgnnSampleIndexRow,
    StgnnSampleMetadata,
    StgnnTensorSample,
    TrainingConversionError,
    assert_no_training_secret,
    default_stgnn_feature_spec,
    feature_spec_hash,
    sanitize_training_payload,
)


def test_default_feature_spec_is_json_friendly_and_hashable() -> None:
    spec = default_stgnn_feature_spec(max_nodes=4, risk_label_horizons_s=[10.0, 5.0, 5.0])

    assert spec.schema_version == TRAINING_SCHEMA_VERSION
    assert spec.variable_node_strategy == "pad_and_mask"
    assert spec.risk_label_horizons_s == [5.0, 10.0]
    assert "theta_sin" in spec.node_features
    assert "edge_distance_m" in spec.edge_features
    assert "collision_label" in spec.risk_targets
    assert len(feature_spec_hash(spec)) == 64
    assert spec.model_dump(mode="json")["max_nodes"] == 4


def test_feature_spec_rejects_empty_features_bad_horizons_and_nan() -> None:
    with pytest.raises(ValidationError):
        StgnnFeatureSpec(
            node_features=[],
            edge_features=["edge_distance_m"],
            traj_targets=["hook_x"],
            risk_targets=["collision_label"],
            risk_label_horizons_s=[5.0],
            max_nodes=2,
        )

    with pytest.raises(ValidationError):
        default_stgnn_feature_spec(max_nodes=2, risk_label_horizons_s=[0.0])

    with pytest.raises(ValidationError):
        default_stgnn_feature_spec(max_nodes=2, risk_label_horizons_s=[math.nan])


def test_sample_metadata_preserves_traceability_and_rejects_extra_fields() -> None:
    metadata = StgnnSampleMetadata(
        dataset_id="dataset-a",
        split="train",
        scenario_id="scenario-1",
        episode_id="episode-1",
        start_frame=12,
        input_steps=4,
        pred_steps=2,
        stride_steps=1,
        risk_label_horizons_s=[5.0, 10.0],
        source_paths={"trajectories": "episodes/episode-1/data/trajectories.parquet"},
        source_window_index={"row": 7},
        feature_spec_hash="a" * 64,
    )

    payload = metadata.model_dump(mode="json")
    assert payload["dataset_id"] == "dataset-a"
    assert payload["split"] == "train"
    assert payload["episode_id"] == "episode-1"
    assert payload["start_frame"] == 12
    assert payload["schema_version"] == TRAINING_SCHEMA_VERSION

    with pytest.raises(ValidationError):
        StgnnSampleMetadata(
            **payload,
            raw_secret="sk-test-secret",
        )


def test_sample_index_row_validates_dimensions_and_embedded_metadata() -> None:
    row = StgnnSampleIndexRow(
        sample_id="sample-001",
        dataset_id="dataset-a",
        split="train",
        episode_id="episode-1",
        start_frame=0,
        tensor_path=None,
        tensor_offset=None,
        num_nodes=2,
        max_nodes=4,
        input_steps=3,
        pred_steps=2,
        node_feature_dim=25,
        edge_feature_dim=7,
        traj_target_dim=7,
        risk_target_dim=4,
        metadata_json={"dataset_id": "dataset-a", "episode_id": "episode-1"},
    )

    assert row.num_nodes == 2
    assert row.max_nodes == 4
    assert row.model_dump(mode="json")["tensor_path"] is None

    invalid_row = row.model_dump()
    invalid_row.update({"num_nodes": 5, "max_nodes": 4})
    with pytest.raises(ValidationError):
        StgnnSampleIndexRow(**invalid_row)


def test_tensor_sample_validates_shapes_against_metadata_and_spec() -> None:
    spec = default_stgnn_feature_spec(max_nodes=3, risk_label_horizons_s=[5.0, 10.0])
    metadata = StgnnSampleMetadata(
        dataset_id="dataset-a",
        split="train",
        episode_id="episode-1",
        start_frame=0,
        input_steps=2,
        pred_steps=3,
        stride_steps=1,
        risk_label_horizons_s=[5.0, 10.0],
        source_paths={"trajectories": "trajectories.parquet"},
        source_window_index={"row": 0},
        feature_spec_hash=feature_spec_hash(spec),
    )

    sample = StgnnTensorSample(
        metadata=metadata,
        feature_spec=spec,
        X_node=np.zeros((2, 3, len(spec.node_features))),
        X_edge=np.zeros((2, 3, 3, len(spec.edge_features))),
        A_phy=np.zeros((2, 3, 3)),
        Y_traj=np.zeros((3, 3, len(spec.traj_targets))),
        Y_risk=np.zeros((2, 3, 3, len(spec.risk_targets))),
        node_mask=np.array([True, True, False]),
        edge_mask=np.zeros((3, 3), dtype=bool),
        risk_mask=np.zeros((2, 3, 3), dtype=bool),
    )

    assert sample.X_node.shape == (2, 3, len(spec.node_features))
    assert sample.Y_risk.shape == (2, 3, 3, len(spec.risk_targets))

    invalid_sample = sample.model_dump()
    invalid_sample["X_node"] = np.zeros((1, 3, len(spec.node_features)))
    with pytest.raises(ValidationError):
        StgnnTensorSample(**invalid_sample)


def test_conversion_options_and_summary_reject_secret_payloads() -> None:
    spec = default_stgnn_feature_spec(max_nodes=4, risk_label_horizons_s=[5.0])
    options = StgnnConversionOptions(
        dataset_root=Path("runs/datasets/dataset-a"),
        output_root=Path("runs/datasets/dataset-a/training/stgnn"),
        strict=True,
        splits=["train", "val"],
        max_nodes=4,
    )
    summary = StgnnConversionSummary(
        dataset_id="dataset-a",
        sample_counts={"train": 2, "val": 1},
        skipped_counts={},
        num_episodes=2,
        max_nodes=4,
        feature_spec=spec,
        risk_distribution={"safe": 0.75, "collision": 0.25},
    )

    assert options.splits == ["train", "val"]
    assert summary.model_dump(mode="json")["sample_counts"]["train"] == 2

    with pytest.raises(TrainingConversionError) as exc_info:
        assert_no_training_secret(
            {"metadata": {"authorization": "Bearer sk-live-secret"}},
            context="stgnn_summary",
        )

    assert exc_info.value.code == TRAINING_E_SECRET_LEAKAGE
    assert "authorization" in exc_info.value.details["field_path"]


def test_training_conversion_error_sanitizes_raw_secret_values() -> None:
    error = TrainingConversionError(
        TRAINING_E_CONFIG_INVALID,
        "failed with sk-live-secret and Authorization: Bearer token-value",
        details={
            "api_key": "sk-live-secret",
            "nested": {"token": "token-value"},
            "safe": "kept",
        },
    )

    rendered = str(error)
    assert "sk-live-secret" not in rendered
    assert "token-value" not in rendered
    assert "[REDACTED]" in rendered
    assert error.details["safe"] == "kept"

    sanitized = sanitize_training_payload(
        {"path": "https://example.test/data?token=token-value", "safe": "ok"}
    )
    assert "token-value" not in str(sanitized)
