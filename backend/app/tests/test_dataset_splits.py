from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.data.splits import DatasetSplitPlanner
from backend.app.schemas.config import DatasetConfig
from backend.app.schemas.dataset import (
    DATASET_E_INSUFFICIENT_EPISODES,
    DATASET_E_SPLIT_LEAKAGE,
    DatasetBuildError,
    DatasetEpisodeRecord,
    DatasetQualityReport,
    DatasetSplitAssignment,
)
from backend.app.tests.test_config_schema import load_fixture


def _dataset_config() -> DatasetConfig:
    return DatasetConfig.model_validate(load_fixture("dataset_valid.yaml"))


def _episode(
    index: int,
    *,
    layout_hash: str | None = None,
    num_cranes: int = 3,
    high: float = 0.0,
    near_miss: int = 0,
    collision: int = 0,
) -> DatasetEpisodeRecord:
    return DatasetEpisodeRecord(
        episode_id=f"E{index:03d}",
        scenario_id=f"S{index % 3}",
        run_dir=Path(f"runs/E{index:03d}"),
        episode_status="completed",
        duration_s=320.0,
        frame_count=100,
        num_cranes=num_cranes,
        layout_hash=layout_hash or f"L{index % 4}",
        risk_frame_ratio_by_level={"safe": 1.0 - high, "high": high},
        near_miss_count=near_miss,
        collision_count=collision,
    )


def _quality(status: str = "passed") -> DatasetQualityReport:
    return DatasetQualityReport(episode_id="unused", quality_status=status)


def _quality_by_episode(episodes: list[DatasetEpisodeRecord], failed: set[str] | None = None):
    failed = failed or set()
    return {
        episode.episode_id: DatasetQualityReport(
            episode_id=episode.episode_id,
            quality_status="failed" if episode.episode_id in failed else "passed",
        )
        for episode in episodes
    }


def test_split_planner_assigns_stable_splits_and_excludes_failed_quality() -> None:
    episodes = [_episode(index) for index in range(10)]
    reports = _quality_by_episode(episodes, failed={"E009"})

    assignments = DatasetSplitPlanner(config=_dataset_config()).assign(episodes, reports)

    by_episode = {assignment.episode_id: assignment.split for assignment in assignments}
    assert "E009" not in by_episode
    assert len(by_episode) == 9
    repeated = DatasetSplitPlanner(config=_dataset_config()).assign(episodes, reports)
    assert [assignment.model_dump(mode="json") for assignment in assignments] == [
        assignment.model_dump(mode="json") for assignment in repeated
    ]
    assert sum(split == "train" for split in by_episode.values()) >= 1
    assert set(by_episode.values()) <= {
        "train",
        "val",
        "test",
        "test_unseen_layout",
        "test_unseen_num_cranes",
        "test_high_risk",
    }


def test_split_planner_creates_unseen_layout_and_num_cranes_holdouts() -> None:
    episodes = [
        *[_episode(index, layout_hash="L-train", num_cranes=3) for index in range(6)],
        _episode(6, layout_hash="L-unseen", num_cranes=3),
        _episode(7, layout_hash="L-other", num_cranes=5),
    ]

    assignments = DatasetSplitPlanner(config=_dataset_config()).assign(
        episodes,
        _quality_by_episode(episodes),
    )
    by_episode = {assignment.episode_id: assignment.split for assignment in assignments}

    assert by_episode["E006"] == "test_unseen_layout"
    assert by_episode["E007"] == "test_unseen_num_cranes"
    train_layouts = {
        episode.layout_hash
        for episode in episodes
        if by_episode.get(episode.episode_id) == "train"
    }
    assert "L-unseen" not in train_layouts


def test_split_planner_selects_high_risk_holdout() -> None:
    episodes = [_episode(index) for index in range(6)]
    episodes.append(_episode(6, high=0.5, near_miss=2))
    config = _dataset_config().model_copy(
        update={
            "split": _dataset_config().split.model_copy(
                update={
                    "holdout": _dataset_config().split.holdout.model_copy(
                        update={"unseen_layout": False, "unseen_num_cranes": False}
                    )
                }
            )
        }
    )

    assignments = DatasetSplitPlanner(config=config).assign(
        episodes,
        _quality_by_episode(episodes),
    )

    assert {assignment.episode_id: assignment.split for assignment in assignments}["E006"] == (
        "test_high_risk"
    )


def test_split_planner_detects_duplicate_episode_leakage() -> None:
    episodes = [_episode(0), _episode(1)]
    assignments = [
        DatasetSplitAssignment(episode_id="E000", split="train", reason="first"),
        DatasetSplitAssignment(episode_id="E000", split="val", reason="duplicate"),
    ]

    with pytest.raises(DatasetBuildError) as exc_info:
        DatasetSplitPlanner(config=_dataset_config()).validate_no_leakage(
            assignments,
            episodes,
        )

    assert exc_info.value.code == DATASET_E_SPLIT_LEAKAGE


def test_split_planner_fails_when_no_episodes_pass_quality() -> None:
    episodes = [_episode(0), _episode(1)]

    with pytest.raises(DatasetBuildError) as exc_info:
        DatasetSplitPlanner(config=_dataset_config()).assign(
            episodes,
            _quality_by_episode(episodes, failed={"E000", "E001"}),
        )

    assert exc_info.value.code == DATASET_E_INSUFFICIENT_EPISODES


def test_split_manifest_is_json_serializable() -> None:
    episodes = [_episode(index) for index in range(4)]
    planner = DatasetSplitPlanner(config=_dataset_config())
    assignments = planner.assign(episodes, _quality_by_episode(episodes))

    manifest = planner.build_split_manifest(assignments, episodes)

    dumped = json.dumps(manifest)
    assert "api_key" not in dumped
    assert manifest["split_counts"]
