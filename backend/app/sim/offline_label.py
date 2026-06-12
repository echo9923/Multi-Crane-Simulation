from __future__ import annotations

import math
from typing import Sequence

from backend.app.schemas.config import RiskConfig
from backend.app.schemas.risk import (
    OFFLINE_LABEL_E_INVALID_GEOMETRY,
    OfflinePairGeometryDistance,
)
from backend.app.schemas.state import CraneState
from backend.app.sim.collision import point_segment_distance_3d, segment_distance_3d


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


def _validated_point(point: Sequence[float]) -> list[float]:
    if len(point) != 3:
        _raise_invalid_geometry("3D point must have exactly three coordinates")
    values = [float(value) for value in point]
    if not all(math.isfinite(value) for value in values):
        _raise_invalid_geometry("3D point contains non-finite coordinate")
    return values


def _raise_invalid_geometry(reason: str) -> None:
    raise ValueError(f"{OFFLINE_LABEL_E_INVALID_GEOMETRY}: {reason}")
