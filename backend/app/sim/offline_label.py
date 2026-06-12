from __future__ import annotations

import math
from itertools import combinations
from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

from pydantic import Field
from backend.app.schemas.crane import CraneConfig
from backend.app.schemas.config import RiskConfig
from backend.app.schemas.risk import (
    OFFLINE_LABEL_E_EMPTY_TRAJECTORY,
    OFFLINE_LABEL_E_CRANE_ID_MISMATCH,
    OFFLINE_LABEL_E_DUPLICATE_TRAJECTORY_ROW,
    OFFLINE_LABEL_E_INVALID_GEOMETRY,
    OFFLINE_LABEL_E_INVALID_WINDOW,
    OFFLINE_LABEL_E_MISSING_FRAME,
    OFFLINE_LABEL_SCHEMA_VERSION,
    OfflineFutureWindowLabel,
    OfflineLabelError,
    OfflinePairGeometryDistance,
    OfflinePairRiskRecord,
    OfflineRiskLabel,
    RiskBaseModel,
    RiskLevel,
)
from backend.app.schemas.state import CraneState
from backend.app.sim.collision import point_segment_distance_3d, segment_distance_3d


class OfflinePairGeometryDistanceAtTime(RiskBaseModel):
    schema_version: str = OFFLINE_LABEL_SCHEMA_VERSION
    frame: int = Field(ge=0)
    time_s: float = Field(ge=0)
    geometry: OfflinePairGeometryDistance


class OfflineTrajectoryFrame(RiskBaseModel):
    schema_version: str = OFFLINE_LABEL_SCHEMA_VERSION
    episode_id: str
    frame: int = Field(ge=0)
    time_s: float = Field(ge=0)
    crane_states: List[CraneState]


class OfflineEpisodeInput(RiskBaseModel):
    schema_version: str = OFFLINE_LABEL_SCHEMA_VERSION
    episode_id: str
    scenario_id: Optional[str] = None
    trajectory_frames: List[OfflineTrajectoryFrame]
    crane_configs: List[CraneConfig]
    risk_config: RiskConfig
    online_risks: list[object] = Field(default_factory=list)


class OfflineLabelGenerator:
    def __init__(self, *, future_windows_s: Optional[Sequence[float]] = None) -> None:
        self.future_windows_s = list(future_windows_s) if future_windows_s else None

    @classmethod
    def from_config(cls, config: object) -> "OfflineLabelGenerator":
        windows = None
        risk_config = getattr(config, "risk", None)
        if risk_config is not None and hasattr(risk_config, "future_windows_s"):
            windows = risk_config.future_windows_s
        elif hasattr(config, "future_windows_s"):
            windows = getattr(config, "future_windows_s")
        return cls(future_windows_s=windows)

    def generate(
        self,
        *,
        episode_id: str,
        trajectory_frames: Sequence[OfflineTrajectoryFrame],
        crane_configs: Sequence[CraneConfig],
        risk_config: RiskConfig,
        scenario_id: Optional[str] = None,
        online_risks: Optional[Sequence[object]] = None,
    ) -> List[OfflineRiskLabel]:
        del online_risks
        frames = list(trajectory_frames)
        _validate_trajectory_frames(
            episode_id=episode_id,
            trajectory_frames=frames,
            crane_configs=crane_configs,
        )
        if not frames:
            return []

        crane_ids = sorted(state.crane_id for state in frames[0].crane_states)
        pair_series_by_id: Dict[str, List[OfflinePairGeometryDistanceAtTime]] = {
            _pair_id(left, right): [] for left, right in combinations(crane_ids, 2)
        }
        for frame in frames:
            states_by_id = {state.crane_id: state for state in frame.crane_states}
            for crane_i, crane_j in combinations(crane_ids, 2):
                pair_id = _pair_id(crane_i, crane_j)
                geometry = compute_pair_geometry_distances(
                    state_i=states_by_id[crane_i],
                    state_j=states_by_id[crane_j],
                    risk_config=risk_config,
                )
                pair_series_by_id[pair_id].append(
                    OfflinePairGeometryDistanceAtTime(
                        frame=frame.frame,
                        time_s=frame.time_s,
                        geometry=geometry,
                    )
                )

        windows_s = self.future_windows_s or risk_config.future_windows_s
        labels: List[OfflineRiskLabel] = []
        for crane_i, crane_j in combinations(crane_ids, 2):
            pair_id = _pair_id(crane_i, crane_j)
            pair_series = pair_series_by_id[pair_id]
            for index, sample in enumerate(pair_series):
                future_labels = compute_future_window_labels(
                    current_index=index,
                    pair_series=pair_series,
                    windows_s=windows_s,
                    risk_config=risk_config,
                )
                label_5s = future_labels["5s"]
                label_10s = future_labels["10s"]
                labels.append(
                    OfflineRiskLabel(
                        episode_id=episode_id,
                        scenario_id=scenario_id,
                        frame=sample.frame,
                        time_s=sample.time_s,
                        crane_i=crane_i,
                        crane_j=crane_j,
                        pair_id=pair_id,
                        distance_min_raw_now_m=sample.geometry.distance_min_raw_now_m,
                        clearance_min_now_m=sample.geometry.clearance_min_now_m,
                        distance_jib_jib_raw_now_m=(
                            sample.geometry.distance_jib_jib_raw_now_m
                        ),
                        clearance_jib_jib_now_m=(
                            sample.geometry.clearance_jib_jib_now_m
                        ),
                        distance_jib_i_hook_j_raw_now_m=(
                            sample.geometry.distance_jib_i_hook_j_raw_now_m
                        ),
                        clearance_jib_i_hook_j_now_m=(
                            sample.geometry.clearance_jib_i_hook_j_now_m
                        ),
                        distance_jib_j_hook_i_raw_now_m=(
                            sample.geometry.distance_jib_j_hook_i_raw_now_m
                        ),
                        clearance_jib_j_hook_i_now_m=(
                            sample.geometry.clearance_jib_j_hook_i_now_m
                        ),
                        distance_hook_hook_raw_now_m=(
                            sample.geometry.distance_hook_hook_raw_now_m
                        ),
                        clearance_hook_hook_now_m=(
                            sample.geometry.clearance_hook_hook_now_m
                        ),
                        min_clearance_future_5s_m=(
                            label_5s.min_clearance_future_m
                        ),
                        min_clearance_future_10s_m=(
                            label_10s.min_clearance_future_m
                        ),
                        ttc_5s_s=label_5s.ttc_s,
                        ttc_10s_s=label_10s.ttc_s,
                        risk_level_5s=label_5s.risk_level,
                        risk_level_10s=label_10s.risk_level,
                        collision_label_5s=label_5s.collision_label,
                        collision_label_10s=label_10s.collision_label,
                        future_window_labels=future_labels,
                        used_future_truth=True,
                    )
                )
        return sorted(labels, key=lambda item: (item.frame, item.crane_i, item.crane_j))

    def generate_pair_records(
        self,
        *,
        episode_id: str,
        trajectory_frames: Sequence[OfflineTrajectoryFrame],
        crane_configs: Sequence[CraneConfig],
        risk_config: RiskConfig,
        scenario_id: Optional[str] = None,
    ) -> List[OfflinePairRiskRecord]:
        labels = self.generate(
            episode_id=episode_id,
            scenario_id=scenario_id,
            trajectory_frames=trajectory_frames,
            crane_configs=crane_configs,
            risk_config=risk_config,
        )
        return _labels_to_pair_records(labels)

    def generate_many(
        self,
        *,
        episodes: Sequence[OfflineEpisodeInput],
    ) -> List[OfflinePairRiskRecord]:
        records: List[OfflinePairRiskRecord] = []
        for episode in episodes:
            labels = self.generate(
                episode_id=episode.episode_id,
                scenario_id=episode.scenario_id,
                trajectory_frames=episode.trajectory_frames,
                crane_configs=episode.crane_configs,
                risk_config=episode.risk_config,
                online_risks=episode.online_risks,
            )
            records.extend(_labels_to_pair_records(labels))
        return records


def compute_pair_geometry_distances(
    *,
    state_i: CraneState,
    state_j: CraneState,
    risk_config: RiskConfig,
) -> OfflinePairGeometryDistance:
    if state_i.crane_id == state_j.crane_id:
        _raise_invalid_geometry("duplicate crane ids")

    jib_i = (_validated_point(state_i.root_position), _validated_point(state_i.tip_position))
    jib_j = (_validated_point(state_j.root_position), _validated_point(state_j.tip_position))
    hook_i = _validated_point(state_i.hook_position)
    hook_j = _validated_point(state_j.hook_position)
    envelope = risk_config.geometry_envelope

    distance_jib_jib = segment_distance_3d(jib_i[0], jib_i[1], jib_j[0], jib_j[1])
    clearance_jib_jib = clearance_from_raw_distance(
        raw_distance_m=distance_jib_jib,
        radius_a_m=envelope.jib_radius_m,
        radius_b_m=envelope.jib_radius_m,
    )

    distance_jib_i_hook_j = point_segment_distance_3d(hook_j, jib_i[0], jib_i[1])
    clearance_jib_i_hook_j = clearance_from_raw_distance(
        raw_distance_m=distance_jib_i_hook_j,
        radius_a_m=envelope.jib_radius_m,
        radius_b_m=envelope.hook_radius_m,
    )

    distance_jib_j_hook_i = point_segment_distance_3d(hook_i, jib_j[0], jib_j[1])
    clearance_jib_j_hook_i = clearance_from_raw_distance(
        raw_distance_m=distance_jib_j_hook_i,
        radius_a_m=envelope.jib_radius_m,
        radius_b_m=envelope.hook_radius_m,
    )

    distance_hook_hook = point_distance_3d(hook_i, hook_j)
    clearance_hook_hook = clearance_from_raw_distance(
        raw_distance_m=distance_hook_hook,
        radius_a_m=envelope.hook_radius_m,
        radius_b_m=envelope.hook_radius_m,
    )

    best_raw, best_clearance, object_i, object_j = min(
        [
            (distance_jib_jib, clearance_jib_jib, "jib", "jib"),
            (distance_jib_i_hook_j, clearance_jib_i_hook_j, "jib", "hook"),
            (distance_jib_j_hook_i, clearance_jib_j_hook_i, "hook", "jib"),
            (distance_hook_hook, clearance_hook_hook, "hook", "hook"),
        ],
        key=lambda item: item[1],
    )

    return OfflinePairGeometryDistance(
        distance_min_raw_now_m=best_raw,
        clearance_min_now_m=best_clearance,
        distance_jib_jib_raw_now_m=distance_jib_jib,
        clearance_jib_jib_now_m=clearance_jib_jib,
        distance_jib_i_hook_j_raw_now_m=distance_jib_i_hook_j,
        clearance_jib_i_hook_j_now_m=clearance_jib_i_hook_j,
        distance_jib_j_hook_i_raw_now_m=distance_jib_j_hook_i,
        clearance_jib_j_hook_i_now_m=clearance_jib_j_hook_i,
        distance_hook_hook_raw_now_m=distance_hook_hook,
        clearance_hook_hook_now_m=clearance_hook_hook,
        nearest_object_i=object_i,
        nearest_object_j=object_j,
    )


def compute_future_window_label(
    *,
    current_index: int,
    pair_series: Sequence[OfflinePairGeometryDistanceAtTime],
    window_s: float,
    risk_config: RiskConfig,
    d_safe_effective_m: Optional[float] = None,
) -> OfflineFutureWindowLabel:
    if window_s <= 0:
        _raise_window_error("window_s must be positive")
    _validate_pair_series(pair_series)
    if current_index < 0 or current_index >= len(pair_series):
        _raise_missing_frame("current_index out of range")

    current_time_s = pair_series[current_index].time_s
    window_end_s = current_time_s + window_s
    samples = [
        item
        for item in pair_series[current_index:]
        if current_time_s <= item.time_s <= window_end_s
    ]
    if not samples:
        _raise_empty_trajectory("future window has no samples")

    min_clearance = min(item.geometry.clearance_min_now_m for item in samples)
    safe_distance = (
        risk_config.thresholds_m.high
        if d_safe_effective_m is None
        else d_safe_effective_m
    )
    ttc_s = _first_time_to_threshold(
        current_time_s=current_time_s,
        samples=samples,
        threshold_m=safe_distance,
    )
    collision_label = 1 if min_clearance <= 0 else 0
    return OfflineFutureWindowLabel(
        window_s=window_s,
        min_clearance_future_m=min_clearance,
        ttc_s=ttc_s,
        risk_level=_classify_future_risk_level(
            min_clearance_future_m=min_clearance,
            ttc_s=ttc_s,
            thresholds=risk_config.thresholds_m,
        ),
        collision_label=collision_label,
        used_future_truth=True,
    )


def compute_future_window_labels(
    *,
    current_index: int,
    pair_series: Sequence[OfflinePairGeometryDistanceAtTime],
    windows_s: Sequence[float],
    risk_config: RiskConfig,
    d_safe_effective_m: Optional[float] = None,
) -> Dict[str, OfflineFutureWindowLabel]:
    labels: Dict[str, OfflineFutureWindowLabel] = {}
    for window_s in windows_s:
        label = compute_future_window_label(
            current_index=current_index,
            pair_series=pair_series,
            window_s=window_s,
            risk_config=risk_config,
            d_safe_effective_m=d_safe_effective_m,
        )
        labels[_window_key(window_s)] = label
    return labels


def clearance_from_raw_distance(
    *,
    raw_distance_m: float,
    radius_a_m: float,
    radius_b_m: float,
) -> float:
    if not all(math.isfinite(value) for value in [raw_distance_m, radius_a_m, radius_b_m]):
        _raise_invalid_geometry("non-finite distance or radius")
    if raw_distance_m < 0 or radius_a_m < 0 or radius_b_m < 0:
        _raise_invalid_geometry("negative distance or radius")
    return raw_distance_m - radius_a_m - radius_b_m


def point_distance_3d(point_a: Sequence[float], point_b: Sequence[float]) -> float:
    a = _validated_point(point_a)
    b = _validated_point(point_b)
    return math.sqrt(sum((a[index] - b[index]) ** 2 for index in range(3)))


def _first_time_to_threshold(
    *,
    current_time_s: float,
    samples: Sequence[OfflinePairGeometryDistanceAtTime],
    threshold_m: float,
) -> Optional[float]:
    for item in samples:
        if item.geometry.clearance_min_now_m <= threshold_m:
            return item.time_s - current_time_s
    return None


def _classify_future_risk_level(
    *,
    min_clearance_future_m: float,
    ttc_s: Optional[float],
    thresholds,
) -> RiskLevel:
    if min_clearance_future_m <= 0:
        return "collision"
    if min_clearance_future_m <= thresholds.near_miss:
        return "near_miss"
    if min_clearance_future_m <= thresholds.high:
        return "high"
    if ttc_s is not None:
        return "high"
    if min_clearance_future_m <= thresholds.medium:
        return "medium"
    if min_clearance_future_m <= thresholds.low:
        return "low"
    return "safe"


def _validate_pair_series(
    pair_series: Sequence[OfflinePairGeometryDistanceAtTime],
) -> None:
    if not pair_series:
        _raise_empty_trajectory("pair_series must not be empty")
    previous_frame: Optional[int] = None
    previous_time_s: Optional[float] = None
    for item in pair_series:
        if previous_frame is not None and item.frame <= previous_frame:
            _raise_missing_frame("pair_series frames must increase")
        if previous_time_s is not None and item.time_s <= previous_time_s:
            _raise_missing_frame("pair_series time_s must increase")
        previous_frame = item.frame
        previous_time_s = item.time_s


def _validate_trajectory_frames(
    *,
    episode_id: str,
    trajectory_frames: Sequence[OfflineTrajectoryFrame],
    crane_configs: Sequence[CraneConfig],
) -> None:
    if not trajectory_frames:
        _raise_empty_trajectory("trajectory_frames must not be empty")
    config_ids = [config.crane_id for config in crane_configs]
    if len(config_ids) != len(set(config_ids)):
        _raise_duplicate_row("duplicate crane config ids")
    expected_ids = set(config_ids) if config_ids else None
    previous_frame: Optional[int] = None
    previous_time_s: Optional[float] = None
    for item in trajectory_frames:
        if item.episode_id != episode_id:
            _raise_missing_frame("frame episode_id must match requested episode_id")
        if previous_frame is not None and item.frame != previous_frame + 1:
            _raise_missing_frame("trajectory frame index must be continuous")
        if previous_time_s is not None and item.time_s <= previous_time_s:
            _raise_missing_frame("trajectory time_s must increase")
        ids = [state.crane_id for state in item.crane_states]
        if len(ids) != len(set(ids)):
            _raise_duplicate_row("duplicate crane states in frame")
        frame_ids = set(ids)
        if expected_ids is None:
            expected_ids = frame_ids
        elif frame_ids != expected_ids:
            _raise_crane_mismatch("frame crane ids must match expected crane ids")
        previous_frame = item.frame
        previous_time_s = item.time_s


def _labels_to_pair_records(labels: Sequence[OfflineRiskLabel]) -> List[OfflinePairRiskRecord]:
    grouped: Dict[
        Tuple[str, str, Optional[str], str, str, str], List[OfflineRiskLabel]
    ] = defaultdict(list)
    for label in labels:
        grouped[
            (
                label.episode_id,
                label.pair_id,
                label.scenario_id,
                label.crane_i,
                label.crane_j,
                label.pair_id,
            )
        ].append(label)
    records: List[OfflinePairRiskRecord] = []
    for (
        episode_id,
        _pair_key,
        scenario_id,
        crane_i,
        crane_j,
        pair_id,
    ), pair_labels in sorted(grouped.items()):
        records.append(
            OfflinePairRiskRecord(
                episode_id=episode_id,
                scenario_id=scenario_id,
                crane_i=crane_i,
                crane_j=crane_j,
                pair_id=pair_id,
                labels=sorted(pair_labels, key=lambda item: item.frame),
            )
        )
    return records


def _window_key(window_s: float) -> str:
    if not math.isfinite(window_s) or window_s <= 0:
        _raise_window_error("window_s must be positive and finite")
    if float(window_s).is_integer():
        return f"{int(window_s)}s"
    return f"{window_s:g}s"


def _pair_id(crane_id_a: str, crane_id_b: str) -> str:
    left, right = sorted([crane_id_a, crane_id_b])
    return f"{left}-{right}"


def _validated_point(point: Sequence[float]) -> list[float]:
    if len(point) != 3:
        _raise_invalid_geometry("3D point must have exactly three coordinates")
    values = [float(value) for value in point]
    if not all(math.isfinite(value) for value in values):
        _raise_invalid_geometry("3D point contains non-finite coordinate")
    return values


def _raise_invalid_geometry(reason: str) -> None:
    raise ValueError(f"{OFFLINE_LABEL_E_INVALID_GEOMETRY}: {reason}")


def _raise_window_error(reason: str) -> None:
    raise ValueError(f"{OFFLINE_LABEL_E_INVALID_WINDOW}: {reason}")


def _raise_empty_trajectory(reason: str) -> None:
    raise ValueError(f"{OFFLINE_LABEL_E_EMPTY_TRAJECTORY}: {reason}")


def _raise_missing_frame(reason: str) -> None:
    raise ValueError(f"{OFFLINE_LABEL_E_MISSING_FRAME}: {reason}")


def _raise_crane_mismatch(reason: str) -> None:
    raise ValueError(f"{OFFLINE_LABEL_E_CRANE_ID_MISMATCH}: {reason}")


def _raise_duplicate_row(reason: str) -> None:
    raise ValueError(f"{OFFLINE_LABEL_E_DUPLICATE_TRAJECTORY_ROW}: {reason}")
