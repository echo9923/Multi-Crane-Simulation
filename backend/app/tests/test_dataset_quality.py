from __future__ import annotations

import json
import math
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from backend.app.data.catalog import DatasetCatalog
from backend.app.data.quality import DatasetQualityGate


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_parquet(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def _trajectory_rows(*, bad_time: bool = False, missing_crane_row: bool = False, nan: bool = False) -> list[dict]:
    rows: list[dict] = []
    times = {0: 0.0, 1: 0.1, 2: 0.2}
    if bad_time:
        times[2] = 0.05
    for frame in range(3):
        crane_ids = ["C1", "C2"]
        if missing_crane_row and frame == 1:
            crane_ids = ["C1"]
        for crane_id in crane_ids:
            rows.append(
                {
                    "schema_version": "1.0",
                    "episode_id": "episode-001",
                    "frame": frame,
                    "time_s": times[frame],
                    "crane_id": crane_id,
                    "theta_rad": 0.1,
                    "trolley_r_m": 20.0,
                    "hook_h_m": 25.0,
                    "root_x": 0.0,
                    "root_y": 0.0,
                    "root_z": 45.0,
                    "tip_x": math.nan if nan and frame == 1 and crane_id == "C2" else 50.0,
                    "tip_y": 0.0,
                    "tip_z": 45.0,
                    "hook_x": 20.0,
                    "hook_y": 0.0,
                    "hook_z": 25.0,
                }
            )
    return rows


def _pair_rows() -> list[dict]:
    return [
        {
            "schema_version": "1.0",
            "episode_id": "episode-001",
            "frame": frame,
            "time_s": frame * 0.1,
            "crane_i": "C1",
            "crane_j": "C2",
            "clearance_min_now_m": 5.0,
            "min_clearance_future_5s_m": 4.0,
            "risk_level_5s": "safe",
            "collision_label_5s": 0,
        }
        for frame in range(3)
    ]


def _weather_rows() -> list[dict]:
    return [
        {
            "schema_version": "1.0",
            "episode_id": "episode-001",
            "frame": frame,
            "time_s": frame * 0.1,
            "wind_speed_m_s": 2.0,
        }
        for frame in range(3)
    ]


def _run_dir(
    root: Path,
    *,
    bad_time: bool = False,
    missing_trajectories: bool = False,
    missing_crane_row: bool = False,
    nan: bool = False,
    leaked_observation: bool = False,
) -> Path:
    run_dir = root / "episode-001"
    _write_json(
        run_dir / "metadata" / "episode_summary.json",
        {
            "episode_id": "episode-001",
            "scenario_id": "scenario-001",
            "episode_status": "completed",
            "duration_s": 320.0,
            "frame_count": 3,
            "num_cranes": 2,
            "risk_frame_ratio_by_level": {"safe": 1.0},
            "near_miss_count": 0,
            "collision_count": 0,
        },
    )
    _write_json(
        run_dir / "visual" / "episode_manifest.json",
        {
            "episode_id": "episode-001",
            "frame_count": 3,
            "episode_status": "completed",
            "dt": 0.1,
            "cranes": [{"crane_id": "C1"}, {"crane_id": "C2"}],
        },
    )
    _write_jsonl(
        run_dir / "visual" / "frames.jsonl",
        [
            {
                "type": "sim_frame",
                "episode_id": "episode-001",
                "frame": 0,
                "time_s": 0.0,
                "offline_labels": None,
            }
        ],
    )
    observation = {"schema_version": "1.0", "episode_id": "episode-001", "observation": {}}
    if leaked_observation:
        observation["observation"] = {"min_clearance_future_5s_m": 1.0}
    _write_jsonl(run_dir / "logs" / "llm_observations.jsonl", [observation])
    _write_jsonl(run_dir / "logs" / "events.jsonl", [])
    _write_jsonl(run_dir / "replay" / "command_replay.jsonl", [])
    _write_parquet(run_dir / "data" / "pair_risks.parquet", _pair_rows())
    _write_parquet(run_dir / "data" / "graph_edges.parquet", [{"schema_version": "1.0"}])
    _write_parquet(run_dir / "data" / "tasks.parquet", [{"schema_version": "1.0"}])
    _write_parquet(run_dir / "data" / "weather.parquet", _weather_rows())
    if not missing_trajectories:
        _write_parquet(
            run_dir / "data" / "trajectories.parquet",
            _trajectory_rows(
                bad_time=bad_time,
                missing_crane_row=missing_crane_row,
                nan=nan,
            ),
        )
    return run_dir


def _record(run_dir: Path):
    return DatasetCatalog().read_episode(run_dir)


def test_quality_gate_passes_complete_episode_and_writes_report(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    report = DatasetQualityGate().evaluate_episode(_record(run_dir))

    assert report.quality_status == "passed"
    assert report.failed_checks == []
    assert report.metrics["num_frames"] == 3
    assert (run_dir / "metadata" / "quality_report.json").is_file()


def test_quality_gate_fails_missing_required_file(tmp_path: Path) -> None:
    report = DatasetQualityGate().evaluate_episode(
        _record(_run_dir(tmp_path, missing_trajectories=True))
    )

    assert report.quality_status == "failed"
    assert "schema_valid" in report.failed_checks


def test_quality_gate_fails_time_and_frame_completeness_errors(tmp_path: Path) -> None:
    bad_time = DatasetQualityGate().evaluate_episode(
        _record(_run_dir(tmp_path / "bad-time", bad_time=True))
    )
    missing_row = DatasetQualityGate().evaluate_episode(
        _record(_run_dir(tmp_path / "missing-row", missing_crane_row=True))
    )

    assert "time_monotonic" in bad_time.failed_checks
    assert "frame_completeness" in missing_row.failed_checks


def test_quality_gate_fails_nan_and_offline_truth_leak(tmp_path: Path) -> None:
    nan_report = DatasetQualityGate().evaluate_episode(_record(_run_dir(tmp_path / "nan", nan=True)))
    leak_report = DatasetQualityGate().evaluate_episode(
        _record(_run_dir(tmp_path / "leak", leaked_observation=True))
    )

    assert "no_nan_inf" in nan_report.failed_checks
    assert "online_offline_separation" in leak_report.failed_checks
