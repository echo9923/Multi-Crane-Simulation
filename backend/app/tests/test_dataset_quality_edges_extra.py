from __future__ import annotations

import json
from pathlib import Path

from backend.app.data.quality import DatasetQualityGate
from backend.app.tests.test_dataset_quality import (
    _pair_rows,
    _record,
    _run_dir,
    _weather_rows,
    _write_jsonl,
    _write_parquet,
)


def test_quality_gate_fails_pair_risks_missing_middle_frame(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    rows = [row for row in _pair_rows() if row["frame"] != 1]
    _write_parquet(run_dir / "data" / "pair_risks.parquet", rows)

    report = DatasetQualityGate().evaluate_episode(_record(run_dir))

    assert report.quality_status == "failed"
    assert "frame_completeness" in report.failed_checks


def test_quality_gate_fails_weather_missing_middle_frame(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    rows = [row for row in _weather_rows() if row["frame"] != 1]
    _write_parquet(run_dir / "data" / "weather.parquet", rows)

    report = DatasetQualityGate().evaluate_episode(_record(run_dir))

    assert report.quality_status == "failed"
    assert "frame_completeness" in report.failed_checks


def test_quality_gate_fails_case_insensitive_future_truth_leak(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    _write_jsonl(
        run_dir / "logs" / "llm_observations.jsonl",
        [
            {
                "schema_version": "1.0",
                "episode_id": "episode-001",
                "observation": {"Future_Min_Distance_M": 1.25},
            }
        ],
    )

    report = DatasetQualityGate().evaluate_episode(_record(run_dir))

    assert report.quality_status == "failed"
    assert "online_offline_separation" in report.failed_checks


def test_quality_gate_report_round_trips_after_edge_failure(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    _write_parquet(
        run_dir / "data" / "weather.parquet",
        [row for row in _weather_rows() if row["frame"] != 1],
    )

    report = DatasetQualityGate().evaluate_episode(_record(run_dir))
    persisted = json.loads((run_dir / "metadata" / "quality_report.json").read_text())

    assert persisted["episode_id"] == report.episode_id
    assert persisted["failed_checks"] == report.failed_checks
