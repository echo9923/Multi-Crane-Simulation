from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from backend.app.data.window_index import DatasetWindowIndexer
from backend.app.schemas.config import DatasetConfig
from backend.app.schemas.dataset import (
    DATASET_E_WINDOW_INDEX_FAILED,
    DatasetBuildError,
    DatasetEpisodeRecord,
    DatasetSplitAssignment,
    DatasetWindowIndexRow,
)
from backend.app.tests.test_config_schema import load_fixture


def _config(*, sampling_enabled: bool = False, max_ratio: float = 1.0) -> DatasetConfig:
    raw = load_fixture("dataset_valid.yaml")
    raw["windows"] = {
        "input_steps": 2,
        "pred_steps": 2,
        "stride_steps": 2,
        "risk_label_horizons_s": [5, 10],
        "negative_positive_sampling": {
            "enabled": sampling_enabled,
            "max_negative_to_positive_ratio": max_ratio,
        },
    }
    raw["split"]["holdout"] = {"unseen_layout": False, "unseen_num_cranes": False}
    return DatasetConfig.model_validate(raw)


def _write_pair_risks(path: Path, *, positive_frames: set[int] | None = None) -> None:
    positive_frames = positive_frames or set()
    rows = []
    for frame in range(10):
        positive = frame in positive_frames
        rows.append(
            {
                "schema_version": "1.0",
                "episode_id": path.parent.parent.name,
                "frame": frame,
                "time_s": float(frame),
                "crane_i": "C1",
                "crane_j": "C2",
                "risk_level_5s": "high" if positive else "safe",
                "collision_label_5s": 1 if positive else 0,
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


def _episode(tmp_path: Path, episode_id: str, *, frame_count: int = 10, positive_frames: set[int] | None = None):
    run_dir = tmp_path / episode_id
    pair_path = run_dir / "data" / "pair_risks.parquet"
    _write_pair_risks(pair_path, positive_frames=positive_frames)
    return DatasetEpisodeRecord(
        episode_id=episode_id,
        scenario_id="scenario-a",
        run_dir=run_dir,
        episode_status="completed",
        duration_s=float(frame_count),
        frame_count=frame_count,
        num_cranes=2,
        near_miss_count=0,
        collision_count=0,
        source_files={
            "pair_risks": pair_path,
            "trajectories": run_dir / "data" / "trajectories.parquet",
        },
    )


def test_window_indexer_builds_windows_with_expected_ranges(tmp_path: Path) -> None:
    episode = _episode(tmp_path, "E001", frame_count=10, positive_frames={4})
    assignment = DatasetSplitAssignment(episode_id="E001", split="train", reason="fixture")

    rows = DatasetWindowIndexer(config=_config()).build(
        episodes=[episode],
        assignments=[assignment],
    )

    assert [row.start_frame for row in rows] == [0, 2, 4, 6]
    assert all(row.start_frame + row.input_steps + row.pred_steps <= episode.frame_count for row in rows)
    assert rows[0].source_paths["pair_risks"].endswith("pair_risks.parquet")
    assert any(row.is_positive for row in rows)


def test_window_indexer_keeps_episode_split_alignment(tmp_path: Path) -> None:
    episodes = [
        _episode(tmp_path, "E001", positive_frames={4}),
        _episode(tmp_path, "E002", positive_frames=set()),
    ]
    assignments = [
        DatasetSplitAssignment(episode_id="E001", split="train", reason="fixture"),
        DatasetSplitAssignment(episode_id="E002", split="val", reason="fixture"),
    ]

    rows = DatasetWindowIndexer(config=_config()).build(
        episodes=episodes,
        assignments=assignments,
    )

    assert {row.episode_id for row in rows if row.split == "train"} == {"E001"}
    assert {row.episode_id for row in rows if row.split == "val"} == {"E002"}


def test_window_indexer_applies_negative_positive_sampling(tmp_path: Path) -> None:
    episode = _episode(tmp_path, "E001", frame_count=10, positive_frames={4})
    rows = DatasetWindowIndexer(config=_config(sampling_enabled=True, max_ratio=1)).build(
        episodes=[episode],
        assignments=[DatasetSplitAssignment(episode_id="E001", split="train", reason="fixture")],
    )

    positives = [row for row in rows if row.is_positive]
    negatives = [row for row in rows if not row.is_positive]
    assert len(positives) == 1
    assert len(negatives) <= 1


def test_window_indexer_returns_no_rows_for_too_short_episode(tmp_path: Path) -> None:
    episode = _episode(tmp_path, "E001", frame_count=3, positive_frames=set())

    rows = DatasetWindowIndexer(config=_config()).build(
        episodes=[episode],
        assignments=[DatasetSplitAssignment(episode_id="E001", split="train", reason="fixture")],
    )

    assert rows == []


def test_window_indexer_detects_cross_split_assignment_leakage(tmp_path: Path) -> None:
    episode = _episode(tmp_path, "E001", positive_frames=set())
    rows = [
        DatasetWindowIndexRow(
            dataset_id="dataset-a",
            split="train",
            episode_id="E001",
            start_frame=0,
            input_steps=2,
            pred_steps=2,
            stride_steps=2,
            input_start_time_s=0.0,
            prediction_end_time_s=4.0,
            num_cranes=2,
            label_horizons_s=[5.0],
            source_paths={"pair_risks": "pair.parquet"},
            is_positive=False,
        ),
        DatasetWindowIndexRow(
            dataset_id="dataset-a",
            split="val",
            episode_id="E001",
            start_frame=2,
            input_steps=2,
            pred_steps=2,
            stride_steps=2,
            input_start_time_s=2.0,
            prediction_end_time_s=6.0,
            num_cranes=2,
            label_horizons_s=[5.0],
            source_paths={"pair_risks": "pair.parquet"},
            is_positive=False,
        ),
    ]

    with pytest.raises(DatasetBuildError) as exc_info:
        DatasetWindowIndexer(config=_config()).validate_no_window_leakage(
            rows,
            [DatasetSplitAssignment(episode_id=episode.episode_id, split="train", reason="fixture")],
        )

    assert exc_info.value.code == DATASET_E_WINDOW_INDEX_FAILED
