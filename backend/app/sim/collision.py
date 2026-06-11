from __future__ import annotations

import math
from itertools import combinations
from typing import List, Optional, Tuple

from backend.app.schemas.config import RiskConfig
from backend.app.schemas.crane import CraneConfig
from backend.app.schemas.risk import CollisionEvent, RiskObjectType
from backend.app.schemas.state import CraneState


def detect_collisions(
    *,
    crane_states: List[CraneState],
    crane_configs: List[CraneConfig],
    risk_config: RiskConfig,
    source_snapshot_id: str,
    time_s: float,
) -> Optional[CollisionEvent]:
    states_by_id = {state.crane_id: state for state in crane_states}
    configs_by_id = {config.crane_id: config for config in crane_configs}
    if len(states_by_id) != len(crane_states) or len(configs_by_id) != len(crane_configs):
        raise ValueError("duplicate crane ids")
    if set(states_by_id) != set(configs_by_id):
        raise ValueError("crane states and configs must match")
    for crane_id_a, crane_id_b in combinations(sorted(states_by_id), 2):
        event = detect_pair_collision(
            state_a=states_by_id[crane_id_a],
            config_a=configs_by_id[crane_id_a],
            state_b=states_by_id[crane_id_b],
            config_b=configs_by_id[crane_id_b],
            risk_config=risk_config,
            source_snapshot_id=source_snapshot_id,
            time_s=time_s,
        )
        if event is not None:
            return event
    return None


def detect_pair_collision(
    *,
    state_a: CraneState,
    config_a: CraneConfig,
    state_b: CraneState,
    config_b: CraneConfig,
    risk_config: RiskConfig,
    source_snapshot_id: str,
    time_s: float,
) -> Optional[CollisionEvent]:
    for type_a, geom_a, radius_a in _collision_objects(state_a, risk_config):
        for type_b, geom_b, radius_b in _collision_objects(state_b, risk_config):
            distance = _geometry_distance(geom_a, geom_b)
            if distance <= radius_a + radius_b:
                return CollisionEvent(
                    event_id=f"COLLISION_{source_snapshot_id}_{state_a.crane_id}_{state_b.crane_id}",
                    source_snapshot_id=source_snapshot_id,
                    time_s=time_s,
                    crane_id_a=state_a.crane_id,
                    crane_id_b=state_b.crane_id,
                    object_a=type_a,
                    object_b=type_b,
                    distance_m=max(0.0, distance),
                    reason=f"{type_a}_{type_b}_overlap",
                )
    return None


def segments_intersect_2d(
    a0: Tuple[float, float],
    a1: Tuple[float, float],
    b0: Tuple[float, float],
    b1: Tuple[float, float],
) -> bool:
    o1 = _orientation(a0, a1, b0)
    o2 = _orientation(a0, a1, b1)
    o3 = _orientation(b0, b1, a0)
    o4 = _orientation(b0, b1, a1)
    if o1 != o2 and o3 != o4:
        return True
    return (
        (o1 == 0 and _on_segment(a0, b0, a1))
        or (o2 == 0 and _on_segment(a0, b1, a1))
        or (o3 == 0 and _on_segment(b0, a0, b1))
        or (o4 == 0 and _on_segment(b0, a1, b1))
    )


def segment_distance_3d(
    a0: List[float], a1: List[float], b0: List[float], b1: List[float]
) -> float:
    samples = 32
    best = math.inf
    for index in range(samples + 1):
        t = index / samples
        point = [a0[i] + (a1[i] - a0[i]) * t for i in range(3)]
        best = min(best, point_segment_distance_3d(point, b0, b1))
    for index in range(samples + 1):
        t = index / samples
        point = [b0[i] + (b1[i] - b0[i]) * t for i in range(3)]
        best = min(best, point_segment_distance_3d(point, a0, a1))
    return best


def point_segment_distance_3d(
    point: List[float], segment_start: List[float], segment_end: List[float]
) -> float:
    segment = [segment_end[i] - segment_start[i] for i in range(3)]
    length_sq = sum(component * component for component in segment)
    if length_sq == 0:
        return _point_distance(point, segment_start)
    t = sum((point[i] - segment_start[i]) * segment[i] for i in range(3)) / length_sq
    t = max(0.0, min(1.0, t))
    projection = [segment_start[i] + segment[i] * t for i in range(3)]
    return _point_distance(point, projection)


def _collision_objects(
    state: CraneState, risk_config: RiskConfig
) -> List[Tuple[RiskObjectType, object, float]]:
    envelope = risk_config.geometry_envelope
    objects: List[Tuple[RiskObjectType, object, float]] = [
        ("jib", (state.root_position, state.tip_position), envelope.jib_radius_m),
        ("hook", state.hook_position, envelope.hook_radius_m),
    ]
    if state.load_position is not None:
        objects.append(("load", state.load_position, envelope.load_radius_m))
    return objects


def _geometry_distance(geom_a: object, geom_b: object) -> float:
    if _is_segment(geom_a) and _is_segment(geom_b):
        return segment_distance_3d(geom_a[0], geom_a[1], geom_b[0], geom_b[1])
    if _is_segment(geom_a):
        return point_segment_distance_3d(geom_b, geom_a[0], geom_a[1])
    if _is_segment(geom_b):
        return point_segment_distance_3d(geom_a, geom_b[0], geom_b[1])
    return _point_distance(geom_a, geom_b)


def _is_segment(value: object) -> bool:
    return isinstance(value, tuple) and len(value) == 2


def _point_distance(a: List[float], b: List[float]) -> float:
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def _orientation(
    p: Tuple[float, float], q: Tuple[float, float], r: Tuple[float, float]
) -> int:
    value = (q[1] - p[1]) * (r[0] - q[0]) - (q[0] - p[0]) * (r[1] - q[1])
    if abs(value) < 1e-9:
        return 0
    return 1 if value > 0 else 2


def _on_segment(
    p: Tuple[float, float], q: Tuple[float, float], r: Tuple[float, float]
) -> bool:
    return (
        min(p[0], r[0]) - 1e-9 <= q[0] <= max(p[0], r[0]) + 1e-9
        and min(p[1], r[1]) - 1e-9 <= q[1] <= max(p[1], r[1]) + 1e-9
    )
