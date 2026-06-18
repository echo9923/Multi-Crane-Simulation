from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from backend.app.data.catalog import DatasetCatalog
from backend.app.data.dataset_builder import DatasetBuilder
from backend.app.data.quality import DatasetQualityGate
from backend.app.data.splits import DatasetSplitPlanner
from backend.app.data.window_index import DatasetWindowIndexer
from backend.app.schemas.config import DatasetConfig
from backend.app.schemas.dataset import DatasetBuildOptions, DatasetSummary, assert_no_secret_payload
from backend.app.tests.test_config_schema import load_fixture


def _config() -> DatasetConfig:
    raw = load_fixture("dataset_valid.yaml")
    raw["sources"] = [
        {
            "scenario_ref": "unused-scenario.yaml",
            "experiment_template_ref": "unused-experiment.yaml",
            "num_episodes": 3,
        }
    ]
    raw["windows"] = {
        "input_steps": 2,
        "pred_steps": 2,
        "stride_steps": 2,
        "risk_label_horizons_s": [5, 10],
        "negative_positive_sampling": {
            "enabled": False,
            "max_negative_to_positive_ratio": 5,
        },
    }
    raw["split"]["holdout"] = {"unseen_layout": False, "unseen_num_cranes": False}
    return DatasetConfig.model_validate(raw)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _write_parquet(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def _episode(root: Path, episode_id: str, *, failed: bool = False, high: bool = False) -> Path:
    run_dir = root / episode_id
    _write_json(
        run_dir / "metadata" / "episode_summary.json",
        {
            "episode_id": episode_id,
            "scenario_id": "scenario-a",
            "episode_status": "completed",
            "duration_s": 320.0,
            "frame_count": 8,
            "num_cranes": 2,
            "scenario_class": "overlap_safe",
            "risk_frame_ratio_by_level": {"safe": 0.8, "high": 0.2 if high else 0.0},
            "near_miss_count": 1 if high else 0,
            "collision_count": 0,
            "operator_profile_distribution": {"normal": 2},
        },
    )
    _write_json(
        run_dir / "visual" / "episode_manifest.json",
        {
            "episode_id": episode_id,
            "scenario_id": "scenario-a",
            "episode_status": "completed",
            "frame_count": 8,
            "dt": 1.0,
            "cranes": [{"crane_id": "C1"}, {"crane_id": "C2"}],
        },
    )
    _write_jsonl(
        run_dir / "visual" / "frames.jsonl",
        [{"type": "sim_frame", "episode_id": episode_id, "frame": 0, "offline_labels": None}],
    )
    _write_jsonl(run_dir / "logs" / "llm_observations.jsonl", [])
    _write_jsonl(run_dir / "logs" / "events.jsonl", [])
    _write_jsonl(run_dir / "replay" / "command_replay.jsonl", [])
    pair_rows = [
        {
            "schema_version": "1.0",
            "episode_id": episode_id,
            "frame": frame,
            "time_s": float(frame),
            "crane_i": "C1",
            "crane_j": "C2",
            "risk_level_5s": "high" if high and frame == 4 else "safe",
            "collision_label_5s": 0,
            "min_clearance_future_5s_m": 1.0,
        }
        for frame in range(8)
    ]
    trajectory_rows = [
        {
            "schema_version": "1.0",
            "episode_id": episode_id,
            "frame": frame,
            "time_s": float(frame),
            "crane_id": crane_id,
            "trolley_r_m": 20.0,
            "hook_h_m": 25.0,
            "root_x": 0.0,
            "root_y": 0.0,
            "root_z": 45.0,
            "tip_x": 50.0,
            "tip_y": 0.0,
            "tip_z": 45.0,
            "hook_x": 20.0,
            "hook_y": 0.0,
            "hook_z": 25.0,
        }
        for frame in range(8)
        for crane_id in ("C1", "C2")
    ]
    _write_parquet(run_dir / "data" / "pair_risks.parquet", pair_rows)
    _write_parquet(run_dir / "data" / "graph_edges.parquet", [{"schema_version": "1.0"}])
    _write_parquet(run_dir / "data" / "tasks.parquet", [{"schema_version": "1.0"}])
    _write_parquet(
        run_dir / "data" / "weather.parquet",
        [
            {"schema_version": "1.0", "episode_id": episode_id, "frame": frame, "time_s": float(frame)}
            for frame in range(8)
        ],
    )
    if not failed:
        _write_parquet(run_dir / "data" / "trajectories.parquet", trajectory_rows)
    return run_dir


def _builder(config: DatasetConfig) -> DatasetBuilder:
    return DatasetBuilder(
        catalog=DatasetCatalog(),
        quality_gate=DatasetQualityGate(),
        split_planner=DatasetSplitPlanner(config=config),
        window_indexer=DatasetWindowIndexer(config=config),
    )


def test_dataset_builder_writes_manifest_summary_indexes_and_splits(tmp_path: Path) -> None:
    source_root = tmp_path / "runs"
    _episode(source_root, "E001", high=True)
    _episode(source_root, "E002")
    _episode(source_root, "E003", failed=True)
    config = _config()

    result = _builder(config).build(
        config=config,
        options=DatasetBuildOptions(
            source_roots=[source_root],
            output_root=tmp_path / "datasets",
            copy_mode="index_only",
        ),
    )

    dataset_dir = tmp_path / "datasets" / config.dataset_id
    assert result.dataset_dir == dataset_dir
    for relative in (
        "metadata/dataset_manifest.json",
        "metadata/dataset_summary.json",
        "metadata/quality_summary.json",
        "metadata/split_manifest.json",
        "index/episodes.parquet",
        "index/windows.parquet",
        "index/files.parquet",
    ):
        assert (dataset_dir / relative).is_file(), relative

    summary = DatasetSummary.model_validate(
        json.loads((dataset_dir / "metadata" / "dataset_summary.json").read_text())
    )
    assert summary.num_episodes == 2
    assert summary.num_quarantined == 1
    assert summary.near_miss_count == 1
    assert summary.window_counts
    assert summary.target_gaps
    assert_no_secret_payload(summary.model_dump(mode="json"), context="summary")

    windows = pq.read_table(dataset_dir / "index" / "windows.parquet").to_pylist()
    assert windows
    split_manifest = json.loads((dataset_dir / "metadata" / "split_manifest.json").read_text())
    split_episode_ids = {item["episode_id"] for item in split_manifest["assignments"]}
    assert "E003" not in split_episode_ids
    assert (dataset_dir / "quarantine" / "E003" / "quality_report.json").is_file()
    train_file = dataset_dir / "splits" / "train" / "episodes.jsonl"
    assert train_file.is_file()


def test_dataset_builder_index_only_records_source_paths_without_copying(tmp_path: Path) -> None:
    source_root = tmp_path / "runs"
    run_dir = _episode(source_root, "E001")
    config = _config()

    result = _builder(config).build(
        config=config,
        options=DatasetBuildOptions(
            source_roots=[source_root],
            output_root=tmp_path / "datasets",
            copy_mode="index_only",
        ),
    )

    files = pq.read_table(result.dataset_dir / "index" / "files.parquet").to_pylist()
    assert any(row["source_path"].endswith("trajectories.parquet") for row in files)
    assert not (result.dataset_dir / "episodes" / "E001").exists()
    assert any(str(run_dir) in row["source_path"] for row in files)
