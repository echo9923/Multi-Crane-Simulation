from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Sequence

import pyarrow.parquet as pq

from backend.app.schemas.dataset import (
    DatasetBuildWarning,
    DatasetEpisodeRecord,
    DatasetQualityReport,
)

QUALITY_CHECKS = (
    "schema_valid",
    "time_monotonic",
    "frame_completeness",
    "no_nan_inf",
    "mechanical_limits_respected",
    "geometry_consistency",
    "online_offline_separation",
    "replay_ready",
    "event_consistency",
)

_REQUIRED_FILES = (
    "trajectories",
    "pair_risks",
    "graph_edges",
    "tasks",
    "weather",
    "episode_summary",
    "episode_manifest",
)

_OFFLINE_TRUTH_KEYS = (
    "offline_labels",
    "future_min_distance",
    "min_clearance_future",
    "collision_label",
    "offline_ttc",
    "future_window",
)


class DatasetQualityGate:
    def __init__(
        self,
        *,
        min_duration_s: float | None = 300.0,
        required_offline_labels: bool = True,
        require_replay: bool = True,
    ) -> None:
        self.min_duration_s = min_duration_s
        self.required_offline_labels = required_offline_labels
        self.require_replay = require_replay

    def evaluate_episode(self, episode: DatasetEpisodeRecord) -> DatasetQualityReport:
        failed: set[str] = set()
        warnings: list[DatasetBuildWarning] = []
        metrics: dict[str, Any] = {
            "episode_id": episode.episode_id,
            "num_cranes": episode.num_cranes,
            "duration_s": episode.duration_s,
        }

        tables: dict[str, list[dict[str, Any]]] = {}
        for role in _REQUIRED_FILES:
            path = episode.source_files.get(role)
            if path is None or not Path(path).is_file():
                failed.add("schema_valid")
                continue
            if str(path).endswith(".parquet"):
                try:
                    tables[role] = _read_parquet_rows(Path(path))
                except Exception:
                    failed.add("schema_valid")

        trajectories = tables.get("trajectories", [])
        pair_risks = tables.get("pair_risks", [])
        weather = tables.get("weather", [])

        if trajectories:
            metrics["num_frames"] = len({row.get("frame") for row in trajectories})
            if not _times_monotonic_by_frame(trajectories):
                failed.add("time_monotonic")
            if not _trajectory_frame_complete(
                trajectories,
                episode.num_cranes,
                frame_count=episode.frame_count,
            ):
                failed.add("frame_completeness")
            if not _finite_rows(trajectories):
                failed.add("no_nan_inf")
            if not _geometry_consistent(trajectories):
                failed.add("geometry_consistency")
            if not _mechanical_limits_respected(trajectories):
                failed.add("mechanical_limits_respected")

        if pair_risks:
            if not _pair_frame_complete(
                pair_risks,
                episode.num_cranes,
                frame_count=episode.frame_count,
            ):
                failed.add("frame_completeness")
            if not _finite_rows(pair_risks):
                failed.add("no_nan_inf")

        if weather:
            if not _weather_frame_complete(weather, frame_count=episode.frame_count):
                failed.add("frame_completeness")
            if not _finite_rows(weather):
                failed.add("no_nan_inf")

        if self.required_offline_labels and pair_risks and not _has_offline_labels(pair_risks):
            failed.add("schema_valid")

        if not _jsonl_ok(episode.run_dir / "logs" / "events.jsonl"):
            failed.add("event_consistency")
        if self.require_replay and not _jsonl_ok(episode.run_dir / "replay" / "command_replay.jsonl"):
            failed.add("replay_ready")
        if _offline_truth_leaked(episode.run_dir / "logs" / "llm_observations.jsonl"):
            failed.add("online_offline_separation")
        if _offline_truth_leaked_in_realtime_frames(episode.run_dir / "visual" / "frames.jsonl"):
            failed.add("online_offline_separation")

        if self.min_duration_s is not None and episode.duration_s < self.min_duration_s:
            warnings.append(
                DatasetBuildWarning(
                    warning_code="DATASET_W_SHORT_EPISODE_INCLUDED",
                    message="episode duration is shorter than the configured minimum",
                    episode_id=episode.episode_id,
                    details={
                        "duration_s": episode.duration_s,
                        "min_duration_s": self.min_duration_s,
                    },
                )
            )

        status = "failed" if failed else ("warning" if warnings else "passed")
        report = DatasetQualityReport(
            episode_id=episode.episode_id,
            quality_status=status,
            failed_checks=sorted(failed),
            warnings=warnings,
            metrics=metrics,
        )
        _write_quality_report(episode.run_dir, report)
        return report

    def evaluate_many(
        self,
        episodes: Sequence[DatasetEpisodeRecord],
    ) -> list[DatasetQualityReport]:
        return [self.evaluate_episode(episode) for episode in episodes]


def _read_parquet_rows(path: Path) -> list[dict[str, Any]]:
    table = pq.read_table(path)
    return table.to_pylist()


def _times_monotonic_by_frame(rows: list[dict[str, Any]]) -> bool:
    times_by_frame: dict[int, float] = {}
    for row in rows:
        frame = row.get("frame")
        time_s = row.get("time_s")
        if frame is None or time_s is None:
            return False
        times_by_frame.setdefault(int(frame), float(time_s))
    ordered = [times_by_frame[frame] for frame in sorted(times_by_frame)]
    return all(later >= earlier for earlier, later in zip(ordered, ordered[1:]))


def _trajectory_frame_complete(
    rows: list[dict[str, Any]],
    num_cranes: int,
    *,
    frame_count: int,
) -> bool:
    by_frame: dict[int, set[str]] = {}
    for row in rows:
        by_frame.setdefault(int(row.get("frame", -1)), set()).add(str(row.get("crane_id")))
    expected_frames = set(range(frame_count))
    return (
        bool(by_frame)
        and set(by_frame) == expected_frames
        and all(len(crane_ids) == num_cranes for crane_ids in by_frame.values())
    )


def _pair_frame_complete(
    rows: list[dict[str, Any]],
    num_cranes: int,
    *,
    frame_count: int,
) -> bool:
    expected = num_cranes * (num_cranes - 1) // 2
    by_frame: dict[int, int] = {}
    for row in rows:
        by_frame[int(row.get("frame", -1))] = by_frame.get(int(row.get("frame", -1)), 0) + 1
    expected_frames = set(range(frame_count))
    return set(by_frame) == expected_frames and all(count == expected for count in by_frame.values())


def _weather_frame_complete(rows: list[dict[str, Any]], *, frame_count: int) -> bool:
    return {int(row.get("frame", -1)) for row in rows} == set(range(frame_count))


def _finite_rows(rows: list[dict[str, Any]]) -> bool:
    for row in rows:
        for value in row.values():
            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                return False
    return True


def _geometry_consistent(rows: list[dict[str, Any]]) -> bool:
    required = ("root_x", "root_y", "root_z", "tip_x", "tip_y", "tip_z", "hook_x", "hook_y", "hook_z")
    for row in rows:
        for field in required:
            if field in row and row[field] is None:
                return False
    return True


def _mechanical_limits_respected(rows: list[dict[str, Any]]) -> bool:
    for row in rows:
        trolley = row.get("trolley_r_m")
        hook_h = row.get("hook_h_m")
        if isinstance(trolley, (int, float)) and trolley < 0:
            return False
        if isinstance(hook_h, (int, float)) and hook_h < 0:
            return False
    return True


def _has_offline_labels(rows: list[dict[str, Any]]) -> bool:
    return any(
        any(str(key).startswith(("min_clearance_future", "collision_label", "ttc_")) for key in row)
        for row in rows
    )


def _jsonl_ok(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        _read_jsonl(path)
    except Exception:
        return False
    return True


def _offline_truth_leaked(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        return any(_contains_offline_truth(row) for row in _read_jsonl(path))
    except Exception:
        return True


def _offline_truth_leaked_in_realtime_frames(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        for row in _read_jsonl(path):
            if row.get("offline_labels") is not None:
                return True
    except Exception:
        return True
    return False


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError("jsonl row must be object")
        rows.append(payload)
    return rows


def _contains_offline_truth(payload: Any) -> bool:
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key).lower()
            if any(part in key_text for part in _OFFLINE_TRUTH_KEYS):
                return True
            if _contains_offline_truth(value):
                return True
    elif isinstance(payload, list):
        return any(_contains_offline_truth(item) for item in payload)
    return False


def _write_quality_report(run_dir: Path, report: DatasetQualityReport) -> None:
    path = run_dir / "metadata" / "quality_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2)
        + "\n",
        encoding="utf-8",
    )


__all__ = ["DatasetQualityGate", "QUALITY_CHECKS"]
