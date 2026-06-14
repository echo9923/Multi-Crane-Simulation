from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from backend.app.data.catalog import DatasetCatalog
from backend.app.schemas.dataset import (
    DATASET_E_CONFIG_INVALID,
    DATASET_E_EPISODE_DISCOVERY_FAILED,
    DATASET_E_SOURCE_NOT_FOUND,
    DatasetBuildError,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_text(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _episode_run(root: Path, episode_id: str, *, scenario_class: str | None = None) -> Path:
    run_dir = root / episode_id
    _write_json(
        run_dir / "metadata" / "episode_summary.json",
        {
            "episode_id": episode_id,
            "scenario_id": "scenario-overlap-safe",
            "experiment_id": "experiment-a",
            "episode_status": "completed",
            "duration_s": 320.0,
            "frame_count": 6400,
            "num_cranes": 3,
            "risk_frame_ratio_by_level": {"safe": 0.7, "high": 0.3},
            "near_miss_count": 2,
            "collision_count": 0,
            "operator_profile_distribution": {"normal": 2, "aggressive": 1},
            **({"scenario_class": scenario_class} if scenario_class else {}),
        },
    )
    _write_json(
        run_dir / "visual" / "episode_manifest.json",
        {
            "episode_id": episode_id,
            "scenario_id": "scenario-overlap-safe",
            "episode_status": "completed",
            "frame_count": 6400,
            "dt": 0.05,
            "cranes": [{"crane_id": "C1"}, {"crane_id": "C2"}, {"crane_id": "C3"}],
        },
    )
    _write_text(
        run_dir / "config" / "resolved_config.yaml",
        yaml.safe_dump(
            {
                "resolved_config_hash": "hash-001",
                "scenario": {
                    "scenario_id": "scenario-overlap-safe",
                    "layout": {"mode": "auto", "num_cranes": 3},
                },
            }
        ),
    )
    for relative in (
        "data/trajectories.parquet",
        "data/pair_risks.parquet",
        "data/graph_edges.parquet",
        "data/tasks.parquet",
        "data/weather.parquet",
        "logs/events.jsonl",
        "replay/command_replay.jsonl",
        "visual/frames.jsonl",
    ):
        _write_text(run_dir / relative, "")
    return run_dir


def _dataset_summary(root: Path, dataset_id: str, *, num_episodes: int = 3) -> Path:
    dataset_dir = root / dataset_id
    _write_json(
        dataset_dir / "metadata" / "dataset_summary.json",
        {
            "dataset_id": dataset_id,
            "created_at": "2026-06-14T10:00:00Z",
            "num_episodes": num_episodes,
            "num_quarantined": 0,
            "split_counts": {"train": num_episodes},
            "window_counts": {"train": 10},
            "risk_distribution": {"safe": 1.0},
            "near_miss_count": 0,
            "collision_count": 0,
        },
    )
    return dataset_dir


def test_discover_episodes_returns_empty_for_empty_root(tmp_path: Path) -> None:
    catalog = DatasetCatalog()

    assert catalog.discover_episodes([tmp_path]) == []


def test_read_episode_maps_l_run_directory_to_dataset_record(tmp_path: Path) -> None:
    run_dir = _episode_run(tmp_path, "episode-001", scenario_class="overlap_safe")
    catalog = DatasetCatalog()

    record = catalog.read_episode(run_dir)

    assert record.episode_id == "episode-001"
    assert record.scenario_id == "scenario-overlap-safe"
    assert record.experiment_id == "experiment-a"
    assert record.duration_s == 320.0
    assert record.num_cranes == 3
    assert record.scenario_class == "overlap_safe"
    assert record.resolved_config_hash == "hash-001"
    assert record.layout_hash is not None
    assert record.source_files["trajectories"] == run_dir / "data" / "trajectories.parquet"
    assert "api_key" not in record.model_dump_json()


def test_discover_episodes_sorts_and_honors_max_episodes(tmp_path: Path) -> None:
    _episode_run(tmp_path, "episode-b")
    _episode_run(tmp_path, "episode-a")
    catalog = DatasetCatalog()

    records = catalog.discover_episodes([tmp_path], max_episodes=1)

    assert [record.episode_id for record in records] == ["episode-a"]


def test_discover_skips_directory_without_episode_summary(tmp_path: Path) -> None:
    _episode_run(tmp_path, "episode-a")
    (tmp_path / "not-an-episode" / "metadata").mkdir(parents=True)
    catalog = DatasetCatalog()

    records = catalog.discover_episodes([tmp_path])

    assert [record.episode_id for record in records] == ["episode-a"]


def test_read_episode_rejects_bad_json_and_missing_source_root(tmp_path: Path) -> None:
    run_dir = _episode_run(tmp_path, "episode-a")
    (run_dir / "metadata" / "episode_summary.json").write_text("{bad-json", encoding="utf-8")
    catalog = DatasetCatalog()

    with pytest.raises(DatasetBuildError) as exc_info:
        catalog.read_episode(run_dir)

    assert exc_info.value.code == DATASET_E_EPISODE_DISCOVERY_FAILED

    with pytest.raises(DatasetBuildError) as missing_info:
        catalog.discover_episodes([tmp_path / "missing"])

    assert missing_info.value.code == DATASET_E_SOURCE_NOT_FOUND


def test_dataset_summary_read_and_list_reject_path_traversal(tmp_path: Path) -> None:
    _dataset_summary(tmp_path, "dataset-a", num_episodes=4)
    _dataset_summary(tmp_path, "dataset-b", num_episodes=2)
    catalog = DatasetCatalog(dataset_root=tmp_path)

    summary = catalog.read_dataset_summary("dataset-a")
    items, total = catalog.list_datasets(limit=1, offset=0)

    assert summary.dataset_id == "dataset-a"
    assert total == 2
    assert [item.dataset_id for item in items] == ["dataset-a"]

    with pytest.raises(DatasetBuildError) as exc_info:
        catalog.read_dataset_summary("../secret")

    assert exc_info.value.code == DATASET_E_SOURCE_NOT_FOUND


def test_dataset_summary_rejects_secret_like_payload(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset-a"
    _write_json(
        dataset_dir / "metadata" / "dataset_summary.json",
        {
            "dataset_id": "dataset-a",
            "created_at": "2026-06-14T10:00:00Z",
            "num_episodes": 1,
            "num_quarantined": 0,
            "split_counts": {"train": 1},
            "window_counts": {"train": 1},
            "risk_distribution": {"safe": 1.0},
            "near_miss_count": 0,
            "collision_count": 0,
            "metadata": {"api_key": "sk-secret"},
        },
    )
    catalog = DatasetCatalog(dataset_root=tmp_path)

    with pytest.raises(DatasetBuildError) as exc_info:
        catalog.read_dataset_summary("dataset-a")

    assert exc_info.value.code == DATASET_E_CONFIG_INVALID
