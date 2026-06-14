from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

from backend.app.schemas.config import DatasetConfig
from backend.app.schemas.dataset import (
    DATASET_E_INSUFFICIENT_EPISODES,
    DATASET_E_SPLIT_LEAKAGE,
    DatasetBuildError,
    DatasetEpisodeRecord,
    DatasetQualityReport,
    DatasetSplitAssignment,
    assert_no_secret_payload,
)


class DatasetSplitPlanner:
    def __init__(self, *, config: DatasetConfig) -> None:
        self.config = config

    def assign(
        self,
        episodes: Sequence[DatasetEpisodeRecord],
        quality_reports: Mapping[str, DatasetQualityReport],
    ) -> list[DatasetSplitAssignment]:
        candidates = [
            episode
            for episode in sorted(episodes, key=_episode_sort_key)
            if quality_reports.get(episode.episode_id) is not None
            and quality_reports[episode.episode_id].quality_status != "failed"
        ]
        if not candidates:
            raise DatasetBuildError(
                DATASET_E_INSUFFICIENT_EPISODES,
                "no episodes passed dataset quality gate",
                details={},
            )

        assignments: dict[str, DatasetSplitAssignment] = {}
        remaining = list(candidates)

        high_risk = _first_high_risk(remaining)
        if high_risk is not None:
            _assign(
                assignments,
                high_risk,
                "test_high_risk",
                "highest risk episode reserved for high-risk holdout",
            )
            remaining.remove(high_risk)

        if self.config.split.holdout.unseen_layout:
            episode = _first_unseen_layout_candidate(remaining)
            if episode is not None:
                _assign(
                    assignments,
                    episode,
                    "test_unseen_layout",
                    "layout hash reserved outside train",
                    holdout_flags={"unseen_layout": True},
                )
                remaining.remove(episode)

        if self.config.split.holdout.unseen_num_cranes:
            episode = _first_unseen_num_cranes_candidate(remaining)
            if episode is not None:
                _assign(
                    assignments,
                    episode,
                    "test_unseen_num_cranes",
                    "crane count reserved outside train",
                    holdout_flags={"unseen_num_cranes": True},
                )
                remaining.remove(episode)

        base_assignments = self._assign_base_splits(remaining)
        for assignment in base_assignments:
            assignments[assignment.episode_id] = assignment

        ordered = [assignments[episode.episode_id] for episode in sorted(candidates, key=_episode_sort_key)]
        self.validate_no_leakage(ordered, candidates)
        return ordered

    def validate_no_leakage(
        self,
        assignments: Sequence[DatasetSplitAssignment],
        episodes: Sequence[DatasetEpisodeRecord],
    ) -> None:
        seen: set[str] = set()
        for assignment in assignments:
            if assignment.episode_id in seen:
                raise DatasetBuildError(
                    DATASET_E_SPLIT_LEAKAGE,
                    "episode appears in multiple splits",
                    details={"episode_id": assignment.episode_id},
                )
            seen.add(assignment.episode_id)

        episode_by_id = {episode.episode_id: episode for episode in episodes}
        train_layouts = {
            episode_by_id[assignment.episode_id].layout_hash
            for assignment in assignments
            if assignment.split == "train" and assignment.episode_id in episode_by_id
        }
        train_num_cranes = {
            episode_by_id[assignment.episode_id].num_cranes
            for assignment in assignments
            if assignment.split == "train" and assignment.episode_id in episode_by_id
        }
        for assignment in assignments:
            episode = episode_by_id.get(assignment.episode_id)
            if episode is None:
                raise DatasetBuildError(
                    DATASET_E_SPLIT_LEAKAGE,
                    "split assignment references unknown episode",
                    details={"episode_id": assignment.episode_id},
                )
            if assignment.split == "test_unseen_layout" and episode.layout_hash in train_layouts:
                raise DatasetBuildError(
                    DATASET_E_SPLIT_LEAKAGE,
                    "unseen layout split leaks a train layout",
                    details={"episode_id": episode.episode_id, "layout_hash": episode.layout_hash},
                )
            if (
                assignment.split == "test_unseen_num_cranes"
                and episode.num_cranes in train_num_cranes
            ):
                raise DatasetBuildError(
                    DATASET_E_SPLIT_LEAKAGE,
                    "unseen crane-count split leaks a train crane count",
                    details={
                        "episode_id": episode.episode_id,
                        "num_cranes": episode.num_cranes,
                    },
                )

    def build_split_manifest(
        self,
        assignments: Sequence[DatasetSplitAssignment],
        episodes: Sequence[DatasetEpisodeRecord],
    ) -> dict[str, Any]:
        episode_by_id = {episode.episode_id: episode for episode in episodes}
        split_counts = Counter(assignment.split for assignment in assignments)
        manifest = {
            "schema_version": "1.0",
            "dataset_id": self.config.dataset_id,
            "split_strategy": self.config.split.strategy,
            "split_counts": dict(sorted(split_counts.items())),
            "assignments": [
                {
                    **assignment.model_dump(mode="json"),
                    "scenario_id": episode_by_id[assignment.episode_id].scenario_id,
                    "layout_hash": episode_by_id[assignment.episode_id].layout_hash,
                    "num_cranes": episode_by_id[assignment.episode_id].num_cranes,
                }
                for assignment in assignments
            ],
        }
        assert_no_secret_payload(manifest, context="split_manifest")
        return manifest

    def _assign_base_splits(
        self,
        episodes: Sequence[DatasetEpisodeRecord],
    ) -> list[DatasetSplitAssignment]:
        if not episodes:
            return []
        total = len(episodes)
        train_count = max(1, int(round(total * self.config.split.train_ratio)))
        val_count = int(round(total * self.config.split.val_ratio))
        if train_count + val_count > total:
            val_count = max(0, total - train_count)
        assignments: list[DatasetSplitAssignment] = []
        for index, episode in enumerate(episodes):
            if index < train_count:
                split = "train"
            elif index < train_count + val_count:
                split = "val"
            else:
                split = "test"
            assignments.append(
                DatasetSplitAssignment(
                    episode_id=episode.episode_id,
                    split=split,
                    reason=f"ratio allocation by {self.config.split.strategy}",
                )
            )
        return assignments


def _assign(
    assignments: dict[str, DatasetSplitAssignment],
    episode: DatasetEpisodeRecord,
    split: str,
    reason: str,
    *,
    holdout_flags: dict[str, bool] | None = None,
) -> None:
    assignments[episode.episode_id] = DatasetSplitAssignment(
        episode_id=episode.episode_id,
        split=split,
        reason=reason,
        holdout_flags=holdout_flags or {},
    )


def _episode_sort_key(episode: DatasetEpisodeRecord) -> tuple[str, str, int, str]:
    return (
        episode.scenario_id or "",
        episode.layout_hash or "",
        episode.num_cranes,
        episode.episode_id,
    )


def _first_high_risk(
    episodes: Sequence[DatasetEpisodeRecord],
) -> DatasetEpisodeRecord | None:
    risky = [
        episode
        for episode in episodes
        if episode.collision_count > 0
        or episode.near_miss_count > 0
        or episode.risk_frame_ratio_by_level.get("high", 0.0) > 0
    ]
    return max(risky, key=_risk_score) if risky else None


def _risk_score(episode: DatasetEpisodeRecord) -> tuple[float, int, int, str]:
    return (
        episode.risk_frame_ratio_by_level.get("high", 0.0),
        episode.near_miss_count,
        episode.collision_count,
        episode.episode_id,
    )


def _first_unseen_layout_candidate(
    episodes: Sequence[DatasetEpisodeRecord],
) -> DatasetEpisodeRecord | None:
    counts = Counter(episode.layout_hash for episode in episodes if episode.layout_hash)
    unique = [episode for episode in episodes if episode.layout_hash and counts[episode.layout_hash] == 1]
    return sorted(unique, key=_episode_sort_key)[0] if unique else None


def _first_unseen_num_cranes_candidate(
    episodes: Sequence[DatasetEpisodeRecord],
) -> DatasetEpisodeRecord | None:
    counts = Counter(episode.num_cranes for episode in episodes)
    unique = [episode for episode in episodes if counts[episode.num_cranes] == 1]
    return sorted(unique, key=_episode_sort_key)[0] if unique else None


__all__ = ["DatasetSplitPlanner"]
