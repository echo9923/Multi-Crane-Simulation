from __future__ import annotations

from collections import defaultdict
from typing import Sequence

import pyarrow.parquet as pq

from backend.app.schemas.config import DatasetConfig
from backend.app.schemas.dataset import (
    DATASET_E_WINDOW_INDEX_FAILED,
    DatasetBuildError,
    DatasetEpisodeRecord,
    DatasetSplitAssignment,
    DatasetWindowIndexRow,
)

_POSITIVE_RISK_LEVELS = {"high", "near_miss", "collision"}


class DatasetWindowIndexer:
    def __init__(self, *, config: DatasetConfig) -> None:
        self.config = config

    def build(
        self,
        *,
        episodes: Sequence[DatasetEpisodeRecord],
        assignments: Sequence[DatasetSplitAssignment],
    ) -> list[DatasetWindowIndexRow]:
        assignment_by_episode = {assignment.episode_id: assignment for assignment in assignments}
        rows: list[DatasetWindowIndexRow] = []
        for episode in sorted(episodes, key=lambda item: item.episode_id):
            assignment = assignment_by_episode.get(episode.episode_id)
            if assignment is None:
                continue
            rows.extend(self._build_episode_windows(episode, assignment))
        rows = self._apply_sampling(rows)
        self.validate_no_window_leakage(rows, assignments)
        return rows

    def validate_no_window_leakage(
        self,
        rows: Sequence[DatasetWindowIndexRow],
        assignments: Sequence[DatasetSplitAssignment],
    ) -> None:
        split_by_episode: dict[str, str] = {}
        for assignment in assignments:
            existing = split_by_episode.get(assignment.episode_id)
            if existing is not None and existing != assignment.split:
                raise DatasetBuildError(
                    DATASET_E_WINDOW_INDEX_FAILED,
                    "episode has multiple split assignments",
                    details={"episode_id": assignment.episode_id},
                )
            split_by_episode[assignment.episode_id] = assignment.split

        observed_splits: dict[str, str] = {}
        for row in rows:
            expected = split_by_episode.get(row.episode_id)
            if expected is not None and row.split != expected:
                raise DatasetBuildError(
                    DATASET_E_WINDOW_INDEX_FAILED,
                    "window split does not match episode split assignment",
                    details={
                        "episode_id": row.episode_id,
                        "expected": expected,
                        "actual": row.split,
                    },
                )
            existing = observed_splits.get(row.episode_id)
            if existing is not None and existing != row.split:
                raise DatasetBuildError(
                    DATASET_E_WINDOW_INDEX_FAILED,
                    "episode windows appear in multiple splits",
                    details={"episode_id": row.episode_id},
                )
            observed_splits[row.episode_id] = row.split

    def _build_episode_windows(
        self,
        episode: DatasetEpisodeRecord,
        assignment: DatasetSplitAssignment,
    ) -> list[DatasetWindowIndexRow]:
        windows = self.config.windows
        total_steps = windows.input_steps + windows.pred_steps
        if episode.frame_count < total_steps:
            return []
        positive_frames = _positive_frames(episode)
        rows: list[DatasetWindowIndexRow] = []
        for start_frame in range(
            0,
            episode.frame_count - total_steps + 1,
            windows.stride_steps,
        ):
            prediction_start = start_frame + windows.input_steps
            prediction_end = start_frame + total_steps
            rows.append(
                DatasetWindowIndexRow(
                    dataset_id=self.config.dataset_id,
                    split=assignment.split,
                    episode_id=episode.episode_id,
                    scenario_id=episode.scenario_id,
                    start_frame=start_frame,
                    input_steps=windows.input_steps,
                    pred_steps=windows.pred_steps,
                    stride_steps=windows.stride_steps,
                    input_start_time_s=float(start_frame),
                    prediction_end_time_s=float(prediction_end),
                    num_cranes=max(episode.num_cranes, 1),
                    label_horizons_s=list(windows.risk_label_horizons_s),
                    source_paths={
                        role: str(path)
                        for role, path in sorted(episode.source_files.items())
                    },
                    is_positive=any(
                        frame in positive_frames
                        for frame in range(prediction_start, prediction_end)
                    ),
                )
            )
        return rows

    def _apply_sampling(
        self,
        rows: Sequence[DatasetWindowIndexRow],
    ) -> list[DatasetWindowIndexRow]:
        sampling = self.config.windows.negative_positive_sampling
        if not sampling.enabled:
            return list(rows)
        by_split: dict[str, list[DatasetWindowIndexRow]] = defaultdict(list)
        for row in rows:
            by_split[row.split].append(row)

        sampled: list[DatasetWindowIndexRow] = []
        for split, split_rows in sorted(by_split.items()):
            positives = [row for row in split_rows if row.is_positive]
            negatives = [row for row in split_rows if not row.is_positive]
            if positives:
                max_negatives = int(
                    len(positives) * sampling.max_negative_to_positive_ratio
                )
                sampled.extend(positives)
                sampled.extend(negatives[:max_negatives])
            else:
                sampled.extend(negatives[:1])
        return sorted(sampled, key=lambda row: (row.split, row.episode_id, row.start_frame))


def _positive_frames(episode: DatasetEpisodeRecord) -> set[int]:
    path = episode.source_files.get("pair_risks")
    if path is None:
        return set()
    try:
        rows = pq.read_table(path).to_pylist()
    except Exception as exc:
        raise DatasetBuildError(
            DATASET_E_WINDOW_INDEX_FAILED,
            "failed to read pair_risks for window labels",
            details={"episode_id": episode.episode_id, "exception_type": type(exc).__name__},
        ) from exc
    positive: set[int] = set()
    for row in rows:
        frame = row.get("frame")
        if frame is None:
            continue
        if _row_is_positive(row):
            positive.add(int(frame))
    return positive


def _row_is_positive(row: dict) -> bool:
    for key, value in row.items():
        key_text = str(key)
        if key_text.startswith("collision_label") and value == 1:
            return True
        if key_text.startswith("risk_level") and value in _POSITIVE_RISK_LEVELS:
            return True
    return False


__all__ = ["DatasetWindowIndexer"]
