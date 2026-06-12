from __future__ import annotations

import math
from typing import Dict, Sequence

from pydantic import Field
from backend.app.schemas.config import RiskConfig
from backend.app.schemas.risk import (
    OFFLINE_LABEL_E_EMPTY_TRAJECTORY,
    OFFLINE_LABEL_E_INVALID_GEOMETRY,
    OFFLINE_LABEL_E_INVALID_WINDOW,
    OFFLINE_LABEL_E_MISSING_FRAME,
    OFFLINE_LABEL_SCHEMA_VERSION,
    OfflineFutureWindowLabel,
    OfflinePairGeometryDistance,
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
    d_safe_effective_m: float | None = None,
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
    d_safe_effective_m: float | None = None,
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
) -> float | None:
    for item in samples:
        if item.geometry.clearance_min_now_m <= threshold_m:
            return item.time_s - current_time_s
    return None


def _classify_future_risk_level(
    *,
    min_clearance_future_m: float,
    ttc_s: float | None,
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
    previous_frame: int | None = None
    previous_time_s: float | None = None
    for item in pair_series:
        if previous_frame is not None and item.frame <= previous_frame:
            _raise_missing_frame("pair_series frames must increase")
        if previous_time_s is not None and item.time_s <= previous_time_s:
            _raise_missing_frame("pair_series time_s must increase")
        previous_frame = item.frame
        previous_time_s = item.time_s


def _window_key(window_s: float) -> str:
    if not math.isfinite(window_s) or window_s <= 0:
        _raise_window_error("window_s must be positive and finite")
    if float(window_s).is_integer():
        return f"{int(window_s)}s"
    return f"{window_s:g}s"


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
