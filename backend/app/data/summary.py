from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Sequence

from backend.app.schemas.config import DatasetConfig
from backend.app.schemas.dataset import (
    DATASET_W_RISK_TARGET_MISSED,
    DatasetBuildWarning,
    DatasetEpisodeRecord,
    DatasetQualityReport,
    DatasetSummary,
    DatasetWindowIndexRow,
)


def build_dataset_summary(
    *,
    config: DatasetConfig,
    episodes: Sequence[DatasetEpisodeRecord],
    quarantined: Sequence[DatasetEpisodeRecord],
    quality_reports: Sequence[DatasetQualityReport],
    windows: Sequence[DatasetWindowIndexRow],
    source_roots: Sequence[str],
    copy_mode: str,
    git_commit: str | None = None,
) -> DatasetSummary:
    split_counts = Counter(row.split for row in windows)
    window_counts = Counter(row.split for row in windows)
    risk_totals: defaultdict[str, float] = defaultdict(float)
    for episode in episodes:
        for level, ratio in episode.risk_frame_ratio_by_level.items():
            risk_totals[level] += ratio
    episode_count = max(len(episodes), 1)
    risk_distribution = {
        level: value / episode_count for level, value in sorted(risk_totals.items())
    }
    operator_distribution: Counter[str] = Counter()
    scenario_distribution: Counter[str] = Counter()
    cranes_distribution: Counter[str] = Counter()
    for episode in episodes:
        operator_distribution.update(episode.operator_profile_distribution)
        scenario_distribution[episode.scenario_class] += 1
        cranes_distribution[str(episode.num_cranes)] += 1

    warnings = _summary_warnings(episodes=episodes, quality_reports=quality_reports)
    high_actual = risk_distribution.get("high", 0.0)
    targets = {"risk_frame_ratio": {"high_min": 0.03}}
    target_gaps = {"risk_frame_ratio.high_min": high_actual - 0.03}
    if high_actual < 0.03:
        warnings.append(
            DatasetBuildWarning(
                warning_code=DATASET_W_RISK_TARGET_MISSED,
                message="high risk ratio is below configured target",
                details={"target": 0.03, "actual": high_actual},
            )
        )

    return DatasetSummary(
        dataset_id=config.dataset_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        git_commit=git_commit,
        num_episodes=len(episodes),
        num_quarantined=len(quarantined),
        split_counts=dict(sorted(split_counts.items())),
        window_counts=dict(sorted(window_counts.items())),
        risk_distribution=risk_distribution or {"safe": 0.0},
        task_completion_rate=_mean_task_completion_rate(episodes),
        near_miss_count=sum(episode.near_miss_count for episode in episodes),
        collision_count=sum(episode.collision_count for episode in episodes),
        operator_profile_distribution=dict(sorted(operator_distribution.items())),
        scenario_class_distribution=dict(sorted(scenario_distribution.items())),
        num_cranes_distribution=dict(sorted(cranes_distribution.items())),
        targets=targets,
        target_gaps=target_gaps,
        warnings=warnings,
        source_roots=list(source_roots),
        copy_mode=copy_mode,  # type: ignore[arg-type]
    )


def _summary_warnings(
    *,
    episodes: Sequence[DatasetEpisodeRecord],
    quality_reports: Sequence[DatasetQualityReport],
) -> list[DatasetBuildWarning]:
    warnings: list[DatasetBuildWarning] = []
    for report in quality_reports:
        warnings.extend(report.warnings)
    if not episodes:
        warnings.append(
            DatasetBuildWarning(
                warning_code="DATASET_W_EMPTY_DATASET",
                message="no passed episodes are available for the dataset",
            )
        )
    return warnings


def _mean_task_completion_rate(episodes: Sequence[DatasetEpisodeRecord]) -> float | None:
    values = []
    for episode in episodes:
        value = getattr(episode, "task_completion_rate", None)
        if isinstance(value, (int, float)):
            values.append(float(value))
    if not values:
        return None
    return sum(values) / len(values)


__all__ = ["build_dataset_summary"]
