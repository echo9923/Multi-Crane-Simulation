from __future__ import annotations

import math
from itertools import combinations
from typing import Dict, List, Optional, Tuple

from backend.app.schemas.command import ExecutedCommand
from backend.app.schemas.config import (
    GeometryEnvelopeConfig,
    RiskConfig,
    RiskThresholdsConfig,
)
from backend.app.schemas.crane import CraneConfig
from backend.app.schemas.observation import OnlineRiskHint
from backend.app.schemas.risk import OnlineRisk, RiskLevel, RiskObjectType, RiskPairResult
from backend.app.schemas.state import CraneState
from backend.app.schemas.weather import WeatherState
from backend.app.sim.physics import recompute_state_geometry
from backend.app.sim.safety import estimate_axis_velocity

RISK_RANK: Dict[str, int] = {
    "safe": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "near_miss": 4,
    "collision": 5,
}


def evaluate_online_risk(
    *,
    crane_states: List[CraneState],
    crane_configs: List[CraneConfig],
    risk_config: RiskConfig,
    weather_state: WeatherState,
    proposed_commands: Dict[str, ExecutedCommand],
    horizon_s: float = 5.0,
    sample_dt_s: float = 1.0,
) -> OnlineRisk:
    _validate_risk_inputs(
        crane_states=crane_states,
        crane_configs=crane_configs,
        proposed_commands=proposed_commands,
        horizon_s=horizon_s,
        sample_dt_s=sample_dt_s,
    )
    configs_by_id = {config.crane_id: config for config in crane_configs}
    states_by_id = {state.crane_id: state for state in crane_states}

    pairs: List[RiskPairResult] = []
    for crane_id_a, crane_id_b in combinations(sorted(states_by_id), 2):
        pairs.append(
            evaluate_pair_risk(
                state_a=states_by_id[crane_id_a],
                config_a=configs_by_id[crane_id_a],
                command_a=proposed_commands[crane_id_a],
                state_b=states_by_id[crane_id_b],
                config_b=configs_by_id[crane_id_b],
                command_b=proposed_commands[crane_id_b],
                risk_config=risk_config,
                weather_state=weather_state,
                horizon_s=horizon_s,
                sample_dt_s=sample_dt_s,
            )
        )
    global_level = _max_risk_level([pair.risk_level for pair in pairs])
    nearest_pair = min(pairs, key=lambda pair: pair.d_min_online_m, default=None)
    hints = _build_hints_by_crane(pairs)
    nearest_neighbor_by_crane = {
        crane_id: hint.nearest_neighbor for crane_id, hint in hints.items()
    }
    return OnlineRisk(
        risk_id=f"RISK_{weather_state.time_s:.3f}",
        source_snapshot_id=_source_snapshot_id(proposed_commands),
        time_s=weather_state.time_s,
        pairs=pairs,
        global_risk_level=global_level,
        nearest_pair_id=nearest_pair.pair_id if nearest_pair else None,
        nearest_neighbor_by_crane=nearest_neighbor_by_crane,
        hint_by_crane=hints,
    )


def evaluate_pair_risk(
    *,
    state_a: CraneState,
    config_a: CraneConfig,
    command_a: ExecutedCommand,
    state_b: CraneState,
    config_b: CraneConfig,
    command_b: ExecutedCommand,
    risk_config: RiskConfig,
    weather_state: WeatherState,
    horizon_s: float,
    sample_dt_s: float,
) -> RiskPairResult:
    if horizon_s <= 0 or sample_dt_s <= 0:
        raise ValueError("horizon_s and sample_dt_s must be positive")
    distance_now, object_a, object_b = distance_between_cranes(
        state_a=state_a,
        config_a=config_a,
        state_b=state_b,
        config_b=config_b,
        envelope=risk_config.geometry_envelope,
    )
    sampled_distances = [distance_now]
    ttc_hat_s: Optional[float] = None
    d_safe_effective = _effective_safe_distance(
        risk_config=risk_config,
        weather_state=weather_state,
    )
    step_count = int(math.ceil(horizon_s / sample_dt_s))
    for step in range(1, step_count + 1):
        dt_s = min(step * sample_dt_s, horizon_s)
        future_a = extrapolate_state_short_horizon(
            state=state_a, config=config_a, command=command_a, dt_s=dt_s
        )
        future_b = extrapolate_state_short_horizon(
            state=state_b, config=config_b, command=command_b, dt_s=dt_s
        )
        distance, _, _ = distance_between_cranes(
            state_a=future_a,
            config_a=config_a,
            state_b=future_b,
            config_b=config_b,
            envelope=risk_config.geometry_envelope,
        )
        sampled_distances.append(distance)
        if ttc_hat_s is None and distance <= d_safe_effective:
            ttc_hat_s = dt_s

    d_hat_min = min(sampled_distances)
    relative_motion = _relative_motion(
        current=distance_now,
        projected_min=d_hat_min,
        projected_final=sampled_distances[-1],
    )
    risk_level = classify_risk_level(
        d_min_online_m=distance_now,
        d_hat_min_m=d_hat_min,
        ttc_hat_s=ttc_hat_s,
        thresholds_m=risk_config.thresholds_m,
        d_safe_effective_m=d_safe_effective,
    )
    wind_extra = _wind_extra(risk_config=risk_config, weather_state=weather_state)
    return RiskPairResult(
        pair_id=_pair_id(state_a.crane_id, state_b.crane_id),
        crane_id_a=state_a.crane_id,
        crane_id_b=state_b.crane_id,
        time_s=weather_state.time_s,
        d_min_online_m=distance_now,
        d_hat_min_m=d_hat_min,
        ttc_hat_s=ttc_hat_s,
        d_safe_effective_m=d_safe_effective,
        base_threshold_m=risk_config.thresholds_m.high,
        wind_extra_m=wind_extra,
        risk_level=risk_level,
        nearest_object_a=object_a,
        nearest_object_b=object_b,
        relative_motion=relative_motion,
        used_future_truth=False,
        confidence=1.0,
        reasons=[relative_motion] if relative_motion != "stable" else [],
    )


def distance_between_cranes(
    *,
    state_a: CraneState,
    config_a: CraneConfig,
    state_b: CraneState,
    config_b: CraneConfig,
    envelope: GeometryEnvelopeConfig,
) -> Tuple[float, RiskObjectType, RiskObjectType]:
    objects_a = _risk_objects(state_a, config_a, envelope)
    objects_b = _risk_objects(state_b, config_b, envelope)
    best_distance = math.inf
    best_types: Tuple[RiskObjectType, RiskObjectType] = ("unknown", "unknown")
    for type_a, geom_a, radius_a in objects_a:
        for type_b, geom_b, radius_b in objects_b:
            center_distance = _geometry_distance(geom_a, geom_b)
            envelope_distance = max(0.0, center_distance - radius_a - radius_b)
            if envelope_distance < best_distance:
                best_distance = envelope_distance
                best_types = (type_a, type_b)
    return best_distance, best_types[0], best_types[1]


def extrapolate_state_short_horizon(
    *,
    state: CraneState,
    config: CraneConfig,
    command: ExecutedCommand,
    dt_s: float,
) -> CraneState:
    theta = state.theta_rad + estimate_axis_velocity(
        axis="slew",
        direction=command.left_joystick.slew.direction,
        gear=command.left_joystick.slew.gear,
        config=config,
    ) * command.left_joystick.slew.speed_scale * dt_s
    trolley_r = state.trolley_r_m + estimate_axis_velocity(
        axis="trolley",
        direction=command.left_joystick.trolley.direction,
        gear=command.left_joystick.trolley.gear,
        config=config,
    ) * command.left_joystick.trolley.speed_scale * dt_s
    trolley_r = min(max(trolley_r, config.trolley_r_min_m), config.trolley_r_max_m)
    hook_h = state.hook_h_m + estimate_axis_velocity(
        axis="hoist",
        direction=command.right_joystick.hoist.direction,
        gear=command.right_joystick.hoist.gear,
        config=config,
    ) * command.right_joystick.hoist.speed_scale * dt_s
    hook_h = min(max(hook_h, config.hook_h_min_world_m), config.hook_h_max_world_m)
    projected = state.model_copy(
        update={
            "theta_rad": theta,
            "trolley_r_m": trolley_r,
            "hook_h_m": hook_h,
        }
    )
    return recompute_state_geometry(config, projected)


def classify_risk_level(
    *,
    d_min_online_m: float,
    d_hat_min_m: float,
    ttc_hat_s: Optional[float],
    thresholds_m: RiskThresholdsConfig,
    d_safe_effective_m: float,
) -> RiskLevel:
    if d_min_online_m <= 0 or d_hat_min_m <= 0:
        return "collision"
    distance = min(d_min_online_m, d_hat_min_m)
    if distance <= thresholds_m.near_miss:
        return "near_miss"
    if distance <= thresholds_m.high or (
        ttc_hat_s is not None and distance <= d_safe_effective_m
    ):
        return "high"
    if distance <= thresholds_m.medium:
        return "medium"
    if distance <= thresholds_m.low:
        return "low"
    return "safe"


def _risk_objects(
    state: CraneState, config: CraneConfig, envelope: GeometryEnvelopeConfig
) -> List[Tuple[RiskObjectType, object, float]]:
    objects: List[Tuple[RiskObjectType, object, float]] = [
        ("jib", (state.root_position, state.tip_position), envelope.jib_radius_m),
        ("hook", state.hook_position, envelope.hook_radius_m),
    ]
    if state.load_position is not None:
        objects.append(("load", state.load_position, envelope.load_radius_m))
    return objects


def _geometry_distance(geom_a: object, geom_b: object) -> float:
    if _is_segment(geom_a) and _is_segment(geom_b):
        return _segment_distance_3d(geom_a[0], geom_a[1], geom_b[0], geom_b[1])
    if _is_segment(geom_a):
        return _point_segment_distance_3d(geom_b, geom_a[0], geom_a[1])
    if _is_segment(geom_b):
        return _point_segment_distance_3d(geom_a, geom_b[0], geom_b[1])
    return _point_distance_3d(geom_a, geom_b)


def _is_segment(value: object) -> bool:
    return isinstance(value, tuple) and len(value) == 2


def _point_distance_3d(a: List[float], b: List[float]) -> float:
    return math.sqrt(sum((a[index] - b[index]) ** 2 for index in range(3)))


def _point_segment_distance_3d(
    point: List[float], start: List[float], end: List[float]
) -> float:
    segment = [end[index] - start[index] for index in range(3)]
    length_sq = sum(component * component for component in segment)
    if length_sq == 0:
        return _point_distance_3d(point, start)
    t = sum((point[index] - start[index]) * segment[index] for index in range(3))
    t = max(0.0, min(1.0, t / length_sq))
    projection = [start[index] + t * segment[index] for index in range(3)]
    return _point_distance_3d(point, projection)


def _segment_distance_3d(
    a0: List[float], a1: List[float], b0: List[float], b1: List[float]
) -> float:
    samples = 20
    best = math.inf
    for index in range(samples + 1):
        t = index / samples
        point = [a0[i] + (a1[i] - a0[i]) * t for i in range(3)]
        best = min(best, _point_segment_distance_3d(point, b0, b1))
    for index in range(samples + 1):
        t = index / samples
        point = [b0[i] + (b1[i] - b0[i]) * t for i in range(3)]
        best = min(best, _point_segment_distance_3d(point, a0, a1))
    return best


def _effective_safe_distance(
    *, risk_config: RiskConfig, weather_state: WeatherState
) -> float:
    return risk_config.thresholds_m.high + _wind_extra(
        risk_config=risk_config, weather_state=weather_state
    )


def _wind_extra(*, risk_config: RiskConfig, weather_state: WeatherState) -> float:
    factor = risk_config.wind_safe_distance_factor
    if not factor.enabled:
        return 0.0
    wind = weather_state.wind_for_safety_m_s or max(
        weather_state.wind_speed_m_s, weather_state.wind_gust_m_s
    )
    return wind / 10.0 * factor.extra_clearance_per_10m_s_wind_m


def _relative_motion(
    *, current: float, projected_min: float, projected_final: float
) -> str:
    if projected_min < current - 1e-6:
        return "closing"
    if projected_final > current + 1e-6:
        return "opening"
    return "stable"


def _max_risk_level(levels: List[RiskLevel]) -> RiskLevel:
    if not levels:
        return "safe"
    return max(levels, key=lambda level: RISK_RANK[level])


def _build_hints_by_crane(pairs: List[RiskPairResult]) -> Dict[str, OnlineRiskHint]:
    best_by_crane: Dict[str, RiskPairResult] = {}
    for pair in pairs:
        for crane_id in [pair.crane_id_a, pair.crane_id_b]:
            current = best_by_crane.get(crane_id)
            if current is None or pair.d_min_online_m < current.d_min_online_m:
                best_by_crane[crane_id] = pair
    hints: Dict[str, OnlineRiskHint] = {}
    for crane_id, pair in best_by_crane.items():
        nearest = pair.crane_id_b if crane_id == pair.crane_id_a else pair.crane_id_a
        object_type = (
            pair.nearest_object_a
            if crane_id == pair.crane_id_a
            else pair.nearest_object_b
        )
        hints[crane_id] = OnlineRiskHint(
            source="online_risk",
            risk_level=_hint_risk_level(pair.risk_level),
            nearest_neighbor=nearest,
            nearest_object_type=object_type,
            clearance_now_m=pair.d_min_online_m,
            estimated_clearance_next_5s_m=pair.d_hat_min_m,
            relative_motion=pair.relative_motion,
            confidence=pair.confidence,
            suggestion=_suggestion(pair.risk_level),
        )
    return hints


def _hint_risk_level(level: RiskLevel) -> str:
    if level in {"safe", "low"}:
        return "low"
    if level == "medium":
        return "medium"
    if level == "high":
        return "high"
    return "critical"


def _suggestion(level: RiskLevel) -> Optional[str]:
    if level in {"high", "near_miss", "collision"}:
        return "slow down or stop"
    if level == "medium":
        return "increase clearance"
    return None


def _source_snapshot_id(commands: Dict[str, ExecutedCommand]) -> str:
    if not commands:
        return "unknown"
    return next(iter(commands.values())).source_snapshot_id


def _pair_id(crane_id_a: str, crane_id_b: str) -> str:
    left, right = sorted([crane_id_a, crane_id_b])
    return f"{left}-{right}"


def _validate_risk_inputs(
    *,
    crane_states: List[CraneState],
    crane_configs: List[CraneConfig],
    proposed_commands: Dict[str, ExecutedCommand],
    horizon_s: float,
    sample_dt_s: float,
) -> None:
    if horizon_s <= 0 or sample_dt_s <= 0:
        raise ValueError("horizon_s and sample_dt_s must be positive")
    state_ids = [state.crane_id for state in crane_states]
    config_ids = [config.crane_id for config in crane_configs]
    if len(state_ids) != len(set(state_ids)):
        raise ValueError("duplicate crane state ids")
    if len(config_ids) != len(set(config_ids)):
        raise ValueError("duplicate crane config ids")
    if set(state_ids) != set(config_ids):
        raise ValueError("crane states and configs must match")
    if not set(state_ids).issubset(proposed_commands):
        raise ValueError("missing proposed commands")
