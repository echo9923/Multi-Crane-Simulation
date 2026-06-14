from __future__ import annotations

import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.schemas.dataset import (
    DATASET_E_CONFIG_INVALID,
    DATASET_SCHEMA_VERSION,
    DatasetBuildError,
    DatasetBuildOptions,
    DatasetBuildWarning,
    DatasetEpisodeRecord,
    DatasetQualityReport,
    DatasetSplitAssignment,
    DatasetSummary,
    DatasetWindowIndexRow,
    assert_no_secret_payload,
)


def test_dataset_summary_accepts_required_metrics_and_warnings() -> None:
    warning = DatasetBuildWarning(
        warning_code="DATASET_W_RISK_TARGET_MISSED",
        message="high risk ratio below target",
        details={"target": 0.03, "actual": 0.01},
    )

    summary = DatasetSummary(
        dataset_id="tower_crane_llm_dataset_v1",
        created_at="2026-06-14T10:00:00Z",
        git_commit="abc123",
        num_episodes=3,
        num_quarantined=1,
        split_counts={"train": 2, "val": 1},
        window_counts={"train": 12, "val": 4},
        risk_distribution={"safe": 0.8, "high": 0.2},
        task_completion_rate=0.75,
        near_miss_count=2,
        collision_count=0,
        targets={"risk_frame_ratio": {"high_min": 0.03}},
        target_gaps={"risk_frame_ratio.high_min": -0.02},
        warnings=[warning],
    )

    payload = summary.model_dump(mode="json")
    assert payload["schema_version"] == DATASET_SCHEMA_VERSION
    assert payload["dataset_id"] == "tower_crane_llm_dataset_v1"
    assert payload["warnings"][0]["warning_code"] == "DATASET_W_RISK_TARGET_MISSED"


def test_dataset_schema_rejects_extra_fields_and_nan() -> None:
    with pytest.raises(ValidationError):
        DatasetBuildWarning(
            warning_code="DATASET_W_UNKNOWN_SCENARIO_CLASS",
            message="unknown",
            unexpected=True,
        )

    with pytest.raises(ValidationError):
        DatasetEpisodeRecord(
            episode_id="E001",
            run_dir=Path("runs/E001"),
            episode_status="completed",
            duration_s=math.nan,
            frame_count=10,
            num_cranes=2,
            near_miss_count=0,
            collision_count=0,
        )


def test_split_assignment_rejects_unknown_split() -> None:
    with pytest.raises(ValidationError):
        DatasetSplitAssignment(
            episode_id="E001",
            split="window_random",
            reason="bad split",
        )


def test_window_index_requires_positive_steps_and_horizons() -> None:
    with pytest.raises(ValidationError):
        DatasetWindowIndexRow(
            dataset_id="dataset-a",
            split="train",
            episode_id="E001",
            start_frame=0,
            input_steps=0,
            pred_steps=10,
            stride_steps=1,
            input_start_time_s=0.0,
            prediction_end_time_s=1.0,
            num_cranes=2,
            label_horizons_s=[5.0],
            source_paths={"trajectories": "data/trajectories.parquet"},
            is_positive=False,
        )

    with pytest.raises(ValidationError):
        DatasetWindowIndexRow(
            dataset_id="dataset-a",
            split="train",
            episode_id="E001",
            start_frame=0,
            input_steps=10,
            pred_steps=10,
            stride_steps=1,
            input_start_time_s=0.0,
            prediction_end_time_s=1.0,
            num_cranes=2,
            label_horizons_s=[],
            source_paths={"trajectories": "data/trajectories.parquet"},
            is_positive=False,
        )


def test_quality_report_and_build_options_are_json_friendly() -> None:
    report = DatasetQualityReport(
        episode_id="E001",
        quality_status="passed",
        metrics={"num_frames": 100, "num_cranes": 2},
    )
    options = DatasetBuildOptions(
        source_roots=[Path("runs")],
        output_root=Path("runs/datasets"),
        max_episodes=2,
    )

    assert report.model_dump(mode="json")["quality_status"] == "passed"
    assert options.model_dump(mode="json")["copy_mode"] == "index_only"


def test_dataset_build_error_carries_code_and_details() -> None:
    error = DatasetBuildError(
        DATASET_E_CONFIG_INVALID,
        "invalid dataset config",
        details={"field": "split"},
    )

    assert error.code == DATASET_E_CONFIG_INVALID
    assert error.details == {"field": "split"}
    assert "invalid dataset config" in str(error)


def test_secret_payload_scanner_rejects_secret_like_values() -> None:
    with pytest.raises(DatasetBuildError) as exc_info:
        assert_no_secret_payload(
            {
                "dataset_id": "dataset-a",
                "metadata": {"api_key": "sk-secret-value"},
            },
            context="dataset_summary",
        )

    assert exc_info.value.code == DATASET_E_CONFIG_INVALID
    assert "api_key" in exc_info.value.details["field_path"]

    assert_no_secret_payload(
        {
            "dataset_id": "dataset-a",
            "metadata": {"key_masked": "sk-***-1234", "provider": "mock"},
        },
        context="dataset_summary",
    )
