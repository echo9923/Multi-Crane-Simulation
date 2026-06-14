from __future__ import annotations

import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.schemas.dataset import DatasetWindowIndexRow
from backend.app.schemas.training import (
    TRAINING_E_SECRET_LEAKAGE,
    StgnnConversionSummary,
    StgnnSampleIndexRow,
    TrainingConversionError,
    default_stgnn_feature_spec,
)
from backend.app.training.metadata import (
    ConversionSummaryBuilder,
    SampleMetadataBuilder,
    build_sample_index_row,
)


def test_sample_metadata_builder_preserves_traceability_and_stable_sample_id() -> None:
    spec = default_stgnn_feature_spec(max_nodes=4, risk_label_horizons_s=[5.0])
    metadata = SampleMetadataBuilder().build(
        window=_window(),
        feature_spec=spec,
        source_paths={
            "trajectories": Path("episodes/E001/data/trajectories.parquet"),
            "pair_risks": Path("episodes/E001/data/pair_risks.parquet"),
        },
        crane_order=["C1", "C2"],
    )
    sample_id = SampleMetadataBuilder().sample_id(metadata)

    assert metadata.dataset_id == "dataset-a"
    assert metadata.split == "train"
    assert metadata.scenario_id == "scenario-a"
    assert metadata.episode_id == "E001"
    assert metadata.start_frame == 10
    assert metadata.source_paths["trajectories"] == "episodes/E001/data/trajectories.parquet"
    assert metadata.source_window_index["crane_order"] == ["C1", "C2"]
    assert sample_id == SampleMetadataBuilder().sample_id(metadata)

    other_spec = default_stgnn_feature_spec(max_nodes=5, risk_label_horizons_s=[5.0])
    other_metadata = SampleMetadataBuilder().build(
        window=_window(),
        feature_spec=other_spec,
        source_paths={"trajectories": Path("episodes/E001/data/trajectories.parquet")},
        crane_order=["C1", "C2"],
    )
    assert sample_id != SampleMetadataBuilder().sample_id(other_metadata)


def test_sample_metadata_builder_rejects_secret_like_source_path() -> None:
    with pytest.raises(TrainingConversionError) as exc_info:
        SampleMetadataBuilder().build(
            window=_window(),
            feature_spec=default_stgnn_feature_spec(max_nodes=4, risk_label_horizons_s=[5.0]),
            source_paths={
                "trajectories": Path("episodes/E001/data/trajectories.parquet?token=raw-secret")
            },
            crane_order=["C1", "C2"],
        )

    assert exc_info.value.code == TRAINING_E_SECRET_LEAKAGE


def test_build_sample_index_row_records_dimensions_and_tensor_location() -> None:
    spec = default_stgnn_feature_spec(max_nodes=4, risk_label_horizons_s=[5.0])
    metadata = SampleMetadataBuilder().build(
        window=_window(),
        feature_spec=spec,
        source_paths={"trajectories": Path("trajectories.parquet")},
        crane_order=["C1", "C2"],
    )
    row = build_sample_index_row(
        metadata=metadata,
        feature_spec=spec,
        num_nodes=2,
        tensor_path=Path("tensors/train/samples.npz"),
        tensor_offset=3,
    )

    assert isinstance(row, StgnnSampleIndexRow)
    assert row.sample_id == SampleMetadataBuilder().sample_id(metadata)
    assert row.tensor_path == "tensors/train/samples.npz"
    assert row.tensor_offset == 3
    assert row.node_feature_dim == len(spec.node_features)
    assert row.edge_feature_dim == len(spec.edge_features)
    assert row.traj_target_dim == len(spec.traj_targets)
    assert row.risk_target_dim == len(spec.risk_targets)


def test_conversion_summary_builder_counts_splits_and_skips() -> None:
    spec = default_stgnn_feature_spec(max_nodes=4, risk_label_horizons_s=[5.0])
    rows = [
        _sample_row("s1", split="train", spec=spec),
        _sample_row("s2", split="train", spec=spec),
        _sample_row("s3", split="val", spec=spec),
    ]
    summary = ConversionSummaryBuilder().build(
        dataset_id="dataset-a",
        samples=rows,
        feature_spec=spec,
        skipped_counts={"test": 1},
        risk_distribution={"safe": 0.75, "collision": 0.25},
        warnings=[],
    )

    assert isinstance(summary, StgnnConversionSummary)
    assert summary.sample_counts == {"train": 2, "val": 1}
    assert summary.skipped_counts == {"test": 1}
    assert summary.num_episodes == 1
    assert summary.max_nodes == 4
    assert summary.risk_distribution["collision"] == 0.25


def test_conversion_summary_builder_rejects_secret_warning_and_nan_distribution() -> None:
    spec = default_stgnn_feature_spec(max_nodes=4, risk_label_horizons_s=[5.0])
    rows = [_sample_row("s1", split="train", spec=spec)]

    with pytest.raises(TrainingConversionError) as exc_info:
        ConversionSummaryBuilder().build(
            dataset_id="dataset-a",
            samples=rows,
            feature_spec=spec,
            warnings=[{"authorization": "Bearer sk-secret"}],
        )
    assert exc_info.value.code == TRAINING_E_SECRET_LEAKAGE

    with pytest.raises(ValidationError):
        ConversionSummaryBuilder().build(
            dataset_id="dataset-a",
            samples=rows,
            feature_spec=spec,
            risk_distribution={"safe": math.nan},
        )


def _sample_row(sample_id: str, *, split: str, spec) -> StgnnSampleIndexRow:
    return StgnnSampleIndexRow(
        sample_id=sample_id,
        dataset_id="dataset-a",
        split=split,
        episode_id="E001",
        start_frame=0,
        tensor_path=None,
        tensor_offset=None,
        num_nodes=2,
        max_nodes=spec.max_nodes,
        input_steps=2,
        pred_steps=2,
        node_feature_dim=len(spec.node_features),
        edge_feature_dim=len(spec.edge_features),
        traj_target_dim=len(spec.traj_targets),
        risk_target_dim=len(spec.risk_targets),
        metadata_json={"dataset_id": "dataset-a", "episode_id": "E001"},
    )


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
        prediction_end_time_s=7.5,
        num_cranes=2,
        label_horizons_s=[5.0],
        source_paths={"trajectories": "trajectories.parquet"},
    )
