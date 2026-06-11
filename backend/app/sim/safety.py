from __future__ import annotations

import math
from typing import Literal, Optional

from backend.app.schemas.command import (
    ExecutedAxisCommand,
    ExecutedCommand,
    ExecutedLeftJoystickCommand,
    ExecutedRightJoystickCommand,
    ParsedCommand,
)
from backend.app.schemas.config import ForbiddenZonePolicyConfig, RiskConfig, ZoneConfig
from backend.app.schemas.crane import CraneConfig
from backend.app.schemas.enums import ForbiddenZonePolicyMode, SafetyMode
from backend.app.schemas.risk import (
    SAFETY_E_INVALID_STATE,
    SAFETY_E_SNAPSHOT_MISMATCH,
    SAFETY_E_UNSUPPORTED_ZONE,
    ForbiddenZoneResult,
    InterventionRecord,
    MechanicalLimitResult,
    SafetyEvent,
    SafetyPipelineResult,
)
from backend.app.schemas.state import CraneState
from backend.app.schemas.weather import WeatherState

GEAR_TO_SPEED_SCALE = {
    0: 0.0,
    1: 0.2,
    2: 0.4,
    3: 0.6,
    4: 0.8,
    5: 1.0,
}
FORBIDDEN_ZONE_SEGMENT_SAMPLES = 12


class MechanicalSafetyError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str = SAFETY_E_INVALID_STATE,
        crane_id: Optional[str] = None,
        field_path: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.category = "episode_failed"
        self.episode_status = "failed_invalid_state"
        self.crane_id = crane_id
        self.field_path = field_path


def apply_mechanical_safety(
    *,
    command: ParsedCommand,
    state: CraneState,
    config: CraneConfig,
    dt_s: float,
) -> tuple[ExecutedCommand, MechanicalLimitResult]:
    _validate_inputs(command=command, state=state, config=config, dt_s=dt_s)

    slew = ExecutedAxisCommand(
        direction=command.left_joystick.slew.direction,
        gear=command.left_joystick.slew.gear,
        source="raw",
    )
    trolley = ExecutedAxisCommand(
        direction=command.left_joystick.trolley.direction,
        gear=command.left_joystick.trolley.gear,
        source="raw",
    )
    hoist = ExecutedAxisCommand(
        direction=command.right_joystick.hoist.direction,
        gear=command.right_joystick.hoist.gear,
        source="raw",
    )
    applied_limits: list[str] = []
    blocked_axes: list[str] = []
    clamped_axes: list[str] = []
    events: list[SafetyEvent] = []

    def record(reason: str, *, axes: list[str], clamp: bool) -> None:
        if reason not in applied_limits:
            applied_limits.append(reason)
        for axis in axes:
            if axis not in blocked_axes:
                blocked_axes.append(axis)
            if clamp and axis not in clamped_axes:
                clamped_axes.append(axis)
        events.append(
            SafetyEvent(
                event_id=f"SAFETY_{command.command_id}_{len(events)}",
                event_type="mechanical_limit",
                time_s=command.time_s,
                crane_id=command.crane_id,
                reason=reason,
            )
        )

    if not command.deadman_pressed:
        slew = _neutral_axis(source="mechanical_limit")
        trolley = _neutral_axis(source="mechanical_limit")
        hoist = _neutral_axis(source="mechanical_limit")
        record("deadman_released", axes=["slew", "trolley", "hoist"], clamp=True)
    elif command.emergency_stop:
        slew = _neutral_axis(source="mechanical_limit")
        trolley = _neutral_axis(source="mechanical_limit")
        hoist = _neutral_axis(source="mechanical_limit")
        record("emergency_stop", axes=["slew", "trolley", "hoist"], clamp=True)
    else:
        if _slew_exceeds_limits(state=state, config=config, direction=slew.direction, gear=slew.gear, dt_s=dt_s):
            slew = _neutral_axis(source="mechanical_limit")
            record("slew_limit", axes=["slew"], clamp=True)

        if command_would_exceed_trolley_limits(
            state=state,
            config=config,
            direction=trolley.direction,
            gear=trolley.gear,
            dt_s=dt_s,
        ):
            trolley = _neutral_axis(source="mechanical_limit")
            record("trolley_limit", axes=["trolley"], clamp=True)

        proposed_radius = state.trolley_r_m + estimate_axis_velocity(
            axis="trolley",
            direction=command.left_joystick.trolley.direction,
            gear=command.left_joystick.trolley.gear,
            config=config,
        ) * dt_s
        if command_would_exceed_load_or_moment(
            state=state,
            config=config,
            proposed_trolley_r_m=proposed_radius,
        ):
            trolley = _neutral_axis(source="mechanical_limit")
            record("overload_prevented", axes=["trolley"], clamp=False)
            record("moment_limit", axes=["trolley"], clamp=False)

        if command_would_exceed_hoist_limits(
            state=state,
            config=config,
            direction=hoist.direction,
            gear=hoist.gear,
            dt_s=dt_s,
        ):
            hoist = _neutral_axis(source="mechanical_limit")
            record("hoist_limit", axes=["hoist"], clamp=True)

    modified = bool(applied_limits)
    result = MechanicalLimitResult(
        crane_id=command.crane_id,
        modified=modified,
        applied_limits=applied_limits,
        blocked_axes=blocked_axes,
        clamped_axes=clamped_axes,
        events=events,
    )
    executed = ExecutedCommand(
        command_id=f"EXEC_{command.command_id}",
        raw_command_id=command.command_id,
        observation_id=command.observation_id,
        source_snapshot_id=command.source_snapshot_id,
        operator_id=command.operator_id,
        crane_id=command.crane_id,
        time_s=command.time_s,
        raw_command=command,
        left_joystick=ExecutedLeftJoystickCommand(slew=slew, trolley=trolley),
        right_joystick=ExecutedRightJoystickCommand(hoist=hoist),
        deadman_pressed=command.deadman_pressed,
        emergency_stop=command.emergency_stop,
        horn=command.horn,
        command_duration_s=command.command_duration_s,
        task_action=command.task_action,
        modified=modified,
        modification_reasons=applied_limits if modified else [],
        mechanical_limit=result,
    )
    return executed, result


def estimate_axis_velocity(
    *,
    axis: Literal["slew", "trolley", "hoist"],
    direction: str,
    gear: int,
    config: CraneConfig,
) -> float:
    scale = GEAR_TO_SPEED_SCALE[gear]
    if direction == "neutral":
        return 0.0
    sign = _direction_sign(direction)
    if axis == "slew":
        return sign * config.model.slew_speed_max_rad_s * scale
    if axis == "trolley":
        return sign * config.model.trolley_speed_max_m_s * scale
    if axis == "hoist":
        return sign * config.model.hoist_speed_max_m_s * scale
    raise ValueError(f"unknown axis: {axis}")


def command_would_exceed_trolley_limits(
    *,
    state: CraneState,
    config: CraneConfig,
    direction: Literal["in", "out", "neutral"],
    gear: int,
    dt_s: float,
) -> bool:
    velocity = estimate_axis_velocity(
        axis="trolley", direction=direction, gear=gear, config=config
    )
    proposed = state.trolley_r_m + velocity * dt_s
    return proposed < config.trolley_r_min_m or proposed > config.trolley_r_max_m


def command_would_exceed_hoist_limits(
    *,
    state: CraneState,
    config: CraneConfig,
    direction: Literal["up", "down", "neutral"],
    gear: int,
    dt_s: float,
) -> bool:
    velocity = estimate_axis_velocity(
        axis="hoist", direction=direction, gear=gear, config=config
    )
    proposed = state.hook_h_m + velocity * dt_s
    return proposed < config.hook_h_min_world_m or proposed > config.hook_h_max_world_m


def command_would_exceed_load_or_moment(
    *,
    state: CraneState,
    config: CraneConfig,
    proposed_trolley_r_m: float,
) -> bool:
    if not state.load_attached or state.load_weight_t <= 0:
        return False
    if not config.model.is_load_allowed(state.load_weight_t, proposed_trolley_r_m):
        return True
    return (
        config.model.moment_at_radius_t_m(state.load_weight_t, proposed_trolley_r_m)
        > config.model.rated_moment_t_m
    )


def apply_forbidden_zone_policy(
    *,
    command: ExecutedCommand,
    state: CraneState,
    config: CraneConfig,
    forbidden_zones: list[ZoneConfig],
    policy: ForbiddenZonePolicyConfig,
    dt_s: float,
) -> tuple[ExecutedCommand, ForbiddenZoneResult]:
    _validate_forbidden_zone_inputs(
        command=command, state=state, config=config, dt_s=dt_s
    )
    if state.load_position is not None:
        current_point = state.load_position
        next_hook = predict_next_hook_position(
            command=command, state=state, config=config, dt_s=dt_s
        )
        delta = [
            next_hook[index] - state.hook_position[index]
            for index in range(3)
        ]
        next_point = [
            state.load_position[index] + delta[index]
            for index in range(3)
        ]
    else:
        current_point = state.hook_position
        next_point = predict_next_hook_position(
            command=command, state=state, config=config, dt_s=dt_s
        )

    zone_ids = movement_enters_forbidden_zone(
        current_point=current_point,
        next_point=next_point,
        zones=forbidden_zones,
    )
    violation = bool(zone_ids)
    blocked = violation and policy.mode is ForbiddenZonePolicyMode.HARD
    events: list[SafetyEvent] = []
    if violation and policy.record_violation:
        events.append(
            SafetyEvent(
                event_id=f"FORBIDDEN_{command.command_id}_0",
                event_type="forbidden_zone",
                time_s=command.time_s,
                crane_id=command.crane_id,
                reason=(
                    "forbidden_zone_blocked"
                    if blocked
                    else "forbidden_zone_violation"
                ),
                details={"zone_ids": list(zone_ids)},
            )
        )
    result = ForbiddenZoneResult(
        crane_id=command.crane_id,
        policy_mode=policy.mode,
        violation_detected=violation,
        blocked=blocked,
        zone_ids=zone_ids,
        events=events,
    )
    if not blocked:
        return command, result

    updated_reasons = list(command.modification_reasons)
    if "forbidden_zone" not in updated_reasons:
        updated_reasons.append("forbidden_zone")
    updated_command = command.model_copy(
        update={
            "left_joystick": ExecutedLeftJoystickCommand(
                slew=command.left_joystick.slew,
                trolley=_neutral_axis(source="forbidden_zone"),
            ),
            "modified": True,
            "modification_reasons": updated_reasons,
            "forbidden_zone": result,
        }
    )
    return updated_command, result


def apply_safety_pipeline(
    *,
    commands: list[ParsedCommand],
    crane_states: list[CraneState],
    crane_configs: list[CraneConfig],
    risk_config: RiskConfig,
    weather_state: WeatherState,
    safety_mode: SafetyMode,
    forbidden_zones: list[ZoneConfig],
    forbidden_zone_policy: ForbiddenZonePolicyConfig,
    source_snapshot_id: str,
    time_s: float,
    dt_s: float,
) -> SafetyPipelineResult:
    _validate_pipeline_inputs(
        commands=commands,
        crane_states=crane_states,
        crane_configs=crane_configs,
        source_snapshot_id=source_snapshot_id,
    )
    states_by_id = {state.crane_id: state for state in crane_states}
    configs_by_id = {config.crane_id: config for config in crane_configs}

    executed_commands: list[ExecutedCommand] = []
    for command in commands:
        mechanical_command, _ = apply_mechanical_safety(
            command=command,
            state=states_by_id[command.crane_id],
            config=configs_by_id[command.crane_id],
            dt_s=dt_s,
        )
        forbidden_command, _ = apply_forbidden_zone_policy(
            command=mechanical_command,
            state=states_by_id[command.crane_id],
            config=configs_by_id[command.crane_id],
            forbidden_zones=forbidden_zones,
            policy=forbidden_zone_policy,
            dt_s=dt_s,
        )
        executed_commands.append(forbidden_command)

    proposed = {command.crane_id: command for command in executed_commands}
    from backend.app.sim.risk import evaluate_online_risk

    online_risk = evaluate_online_risk(
        crane_states=crane_states,
        crane_configs=crane_configs,
        risk_config=risk_config,
        weather_state=weather_state,
        proposed_commands=proposed,
    )
    intervened_commands, interventions = apply_risk_interventions(
        commands=executed_commands,
        online_risk=online_risk,
        safety_mode=safety_mode,
    )
    events = [
        SafetyEvent(
            event_id=f"INTERVENTION_{intervention.intervention_id}",
            event_type="intervention_applied",
            time_s=time_s,
            crane_id=intervention.crane_id,
            reason="intervention_applied",
            details={
                "action": intervention.action,
                "risk_level": intervention.risk_level,
                "pair_ids": intervention.pair_ids,
            },
        )
        for intervention in interventions
        if intervention.modified and safety_mode in {SafetyMode.S2, SafetyMode.S3}
    ]
    return SafetyPipelineResult(
        source_snapshot_id=source_snapshot_id,
        time_s=time_s,
        executed_commands=intervened_commands,
        online_risk=online_risk,
        episode_status="running",
        events=events,
    )


def apply_risk_interventions(
    *,
    commands: list[ExecutedCommand],
    online_risk,
    safety_mode: SafetyMode,
) -> tuple[list[ExecutedCommand], list[InterventionRecord]]:
    risky_pairs_by_crane = _risky_pairs_by_crane(online_risk)
    updated_commands: list[ExecutedCommand] = []
    interventions: list[InterventionRecord] = []
    for command in commands:
        risky_pairs = risky_pairs_by_crane.get(command.crane_id, [])
        if not risky_pairs:
            updated_commands.append(command)
            continue
        highest_level = _highest_pair_level(risky_pairs)
        if safety_mode is SafetyMode.S0:
            updated_commands.append(command)
            continue
        if safety_mode is SafetyMode.S1:
            intervention = _intervention_record(
                command=command,
                safety_mode=safety_mode,
                action="ignored_risk_hint",
                risk_level=highest_level,
                modified=False,
                pair_ids=[pair.pair_id for pair in risky_pairs],
            )
            interventions.append(intervention)
            updated_commands.append(
                command.model_copy(update={"interventions": command.interventions + [intervention]})
            )
            continue
        if safety_mode is SafetyMode.S2 and highest_level in {
            "high",
            "near_miss",
            "collision",
        }:
            intervention = _intervention_record(
                command=command,
                safety_mode=safety_mode,
                action="limit_speed_on_high_risk",
                risk_level=highest_level,
                modified=True,
                pair_ids=[pair.pair_id for pair in risky_pairs],
            )
            interventions.append(intervention)
            updated_commands.append(
                limit_speed_on_high_risk(
                    command=command,
                    reason="risk_intervention",
                    intervention=intervention,
                )
            )
            continue
        if safety_mode is SafetyMode.S3 and highest_level in {
            "high",
            "near_miss",
            "collision",
        }:
            intervention = _intervention_record(
                command=command,
                safety_mode=safety_mode,
                action="force_stop_on_high_risk",
                risk_level=highest_level,
                modified=True,
                pair_ids=[pair.pair_id for pair in risky_pairs],
            )
            interventions.append(intervention)
            updated_commands.append(
                force_stop_on_high_risk(
                    command=command,
                    reason="risk_intervention",
                    intervention=intervention,
                )
            )
            continue
        updated_commands.append(command)
    return updated_commands, interventions


def limit_speed_on_high_risk(
    *,
    command: ExecutedCommand,
    speed_scale: float = 0.5,
    reason: str,
    intervention: InterventionRecord | None = None,
) -> ExecutedCommand:
    reasons = _with_reason(command.modification_reasons, "risk_intervention")
    interventions = command.interventions + (
        [intervention] if intervention is not None else []
    )
    return command.model_copy(
        update={
            "left_joystick": ExecutedLeftJoystickCommand(
                slew=_scale_axis(command.left_joystick.slew, speed_scale),
                trolley=_scale_axis(command.left_joystick.trolley, speed_scale),
            ),
            "right_joystick": ExecutedRightJoystickCommand(
                hoist=_scale_axis(command.right_joystick.hoist, speed_scale)
            ),
            "modified": True,
            "modification_reasons": reasons,
            "interventions": interventions,
        }
    )


def force_stop_on_high_risk(
    *,
    command: ExecutedCommand,
    reason: str,
    intervention: InterventionRecord | None = None,
) -> ExecutedCommand:
    reasons = _with_reason(command.modification_reasons, "risk_intervention")
    interventions = command.interventions + (
        [intervention] if intervention is not None else []
    )
    return command.model_copy(
        update={
            "left_joystick": ExecutedLeftJoystickCommand(
                slew=_neutral_axis(source="risk_intervention"),
                trolley=_neutral_axis(source="risk_intervention"),
            ),
            "right_joystick": ExecutedRightJoystickCommand(
                hoist=_neutral_axis(source="risk_intervention")
            ),
            "modified": True,
            "modification_reasons": reasons,
            "interventions": interventions,
        }
    )


def predict_next_hook_position(
    *,
    command: ExecutedCommand,
    state: CraneState,
    config: CraneConfig,
    dt_s: float,
) -> list[float]:
    _validate_dt(dt_s=dt_s, crane_id=state.crane_id)
    theta = state.theta_rad + estimate_axis_velocity(
        axis="slew",
        direction=command.left_joystick.slew.direction,
        gear=command.left_joystick.slew.gear,
        config=config,
    ) * dt_s
    trolley_r = state.trolley_r_m + estimate_axis_velocity(
        axis="trolley",
        direction=command.left_joystick.trolley.direction,
        gear=command.left_joystick.trolley.gear,
        config=config,
    ) * dt_s
    trolley_r = min(max(trolley_r, config.trolley_r_min_m), config.trolley_r_max_m)
    hook_h = state.hook_h_m + estimate_axis_velocity(
        axis="hoist",
        direction=command.right_joystick.hoist.direction,
        gear=command.right_joystick.hoist.gear,
        config=config,
    ) * dt_s
    hook_h = min(max(hook_h, config.hook_h_min_world_m), config.hook_h_max_world_m)
    return [
        config.base[0] + trolley_r * math.cos(theta),
        config.base[1] + trolley_r * math.sin(theta),
        hook_h,
    ]


def point_in_forbidden_zone(*, point: list[float], zone: ZoneConfig) -> bool:
    if len(point) != 3:
        raise MechanicalSafetyError(
            "point must be a 3D vector",
            error_code=SAFETY_E_INVALID_STATE,
            field_path="point",
        )
    if zone.z_range_m is not None and not (
        zone.z_range_m[0] <= point[2] <= zone.z_range_m[1]
    ):
        return False
    if zone.type == "box":
        if zone.center is None or zone.size is None:
            raise MechanicalSafetyError(
                "box forbidden zone requires center and size",
                error_code=SAFETY_E_INVALID_STATE,
                field_path=f"forbidden_zones.{zone.zone_id}",
            )
        return all(
            abs(point[index] - zone.center[index]) <= zone.size[index] / 2.0
            for index in range(3)
        )
    if zone.type == "polygon":
        if not zone.points:
            raise MechanicalSafetyError(
                "polygon forbidden zone requires points",
                error_code=SAFETY_E_INVALID_STATE,
                field_path=f"forbidden_zones.{zone.zone_id}",
            )
        return _point_in_polygon_2d(point[0], point[1], zone.points)
    raise MechanicalSafetyError(
        f"unsupported forbidden zone type: {zone.type}",
        error_code=SAFETY_E_UNSUPPORTED_ZONE,
        field_path=f"forbidden_zones.{zone.zone_id}.type",
    )


def movement_enters_forbidden_zone(
    *,
    current_point: list[float],
    next_point: list[float],
    zones: list[ZoneConfig],
) -> list[str]:
    hit_ids: list[str] = []
    for zone in zones:
        for sample_index in range(FORBIDDEN_ZONE_SEGMENT_SAMPLES + 1):
            t = sample_index / FORBIDDEN_ZONE_SEGMENT_SAMPLES
            sample = [
                current_point[index] + (next_point[index] - current_point[index]) * t
                for index in range(3)
            ]
            if point_in_forbidden_zone(point=sample, zone=zone):
                hit_ids.append(zone.zone_id)
                break
    return hit_ids


def _slew_exceeds_limits(
    *,
    state: CraneState,
    config: CraneConfig,
    direction: str,
    gear: int,
    dt_s: float,
) -> bool:
    target_velocity = estimate_axis_velocity(
        axis="slew", direction=direction, gear=gear, config=config
    )
    if abs(target_velocity) > config.model.slew_speed_max_rad_s:
        return True
    return (
        abs(target_velocity - state.theta_dot_rad_s)
        > config.model.slew_acc_max_rad_s2 * dt_s
    )


def _point_in_polygon_2d(x: float, y: float, points: list[list[float]]) -> bool:
    inside = False
    j = len(points) - 1
    for i, point_i in enumerate(points):
        xi, yi = point_i[0], point_i[1]
        xj, yj = points[j][0], points[j][1]
        if _point_on_segment_2d(x, y, xi, yi, xj, yj):
            return True
        intersects = (yi > y) != (yj > y) and x <= (
            (xj - xi) * (y - yi) / (yj - yi) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def _point_on_segment_2d(
    x: float, y: float, x1: float, y1: float, x2: float, y2: float
) -> bool:
    cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
    if abs(cross) > 1e-9:
        return False
    return min(x1, x2) - 1e-9 <= x <= max(x1, x2) + 1e-9 and min(
        y1, y2
    ) - 1e-9 <= y <= max(y1, y2) + 1e-9


def _risky_pairs_by_crane(online_risk) -> dict[str, list[object]]:
    result: dict[str, list[object]] = {}
    for pair in online_risk.pairs:
        if pair.risk_level not in {"high", "near_miss", "collision"}:
            continue
        result.setdefault(pair.crane_id_a, []).append(pair)
        result.setdefault(pair.crane_id_b, []).append(pair)
    return result


def _highest_pair_level(pairs: list[object]) -> str:
    ranks = {
        "safe": 0,
        "low": 1,
        "medium": 2,
        "high": 3,
        "near_miss": 4,
        "collision": 5,
    }
    return max((pair.risk_level for pair in pairs), key=lambda level: ranks[level])


def _intervention_record(
    *,
    command: ExecutedCommand,
    safety_mode: SafetyMode,
    action: str,
    risk_level: str,
    modified: bool,
    pair_ids: list[str],
) -> InterventionRecord:
    return InterventionRecord(
        intervention_id=f"{command.command_id}_{action}",
        crane_id=command.crane_id,
        safety_mode=safety_mode,
        risk_level=risk_level,
        action=action,
        modified=modified,
        reason="risk_intervention",
        pair_ids=pair_ids,
    )


def _scale_axis(axis: ExecutedAxisCommand, speed_scale: float) -> ExecutedAxisCommand:
    if axis.direction == "neutral":
        return axis
    return axis.model_copy(
        update={
            "speed_scale": min(axis.speed_scale, speed_scale),
            "source": "risk_intervention",
        }
    )


def _with_reason(reasons: list[str], reason: str) -> list[str]:
    updated = list(reasons)
    if reason not in updated:
        updated.append(reason)
    return updated


def _direction_sign(direction: str) -> float:
    if direction in {"right", "out", "up"}:
        return 1.0
    if direction in {"left", "in", "down"}:
        return -1.0
    return 0.0


def _neutral_axis(
    *, source: Literal["mechanical_limit", "forbidden_zone", "risk_intervention"]
) -> ExecutedAxisCommand:
    return ExecutedAxisCommand(direction="neutral", gear=0, source=source)


def _validate_inputs(
    *,
    command: ParsedCommand,
    state: CraneState,
    config: CraneConfig,
    dt_s: float,
) -> None:
    if not math.isfinite(dt_s) or dt_s <= 0:
        raise MechanicalSafetyError(
            "dt_s must be finite and positive",
            crane_id=command.crane_id,
            field_path="dt_s",
        )
    if command.crane_id != state.crane_id or command.crane_id != config.crane_id:
        raise MechanicalSafetyError(
            "command, state, and config crane_id must match",
            crane_id=command.crane_id,
            field_path="crane_id",
        )


def _validate_dt(*, dt_s: float, crane_id: str) -> None:
    if not math.isfinite(dt_s) or dt_s <= 0:
        raise MechanicalSafetyError(
            "dt_s must be finite and positive",
            crane_id=crane_id,
            field_path="dt_s",
        )


def _validate_forbidden_zone_inputs(
    *,
    command: ExecutedCommand,
    state: CraneState,
    config: CraneConfig,
    dt_s: float,
) -> None:
    _validate_dt(dt_s=dt_s, crane_id=command.crane_id)
    if command.crane_id != state.crane_id or command.crane_id != config.crane_id:
        raise MechanicalSafetyError(
            "command, state, and config crane_id must match",
            crane_id=command.crane_id,
            field_path="crane_id",
        )


def _validate_pipeline_inputs(
    *,
    commands: list[ParsedCommand],
    crane_states: list[CraneState],
    crane_configs: list[CraneConfig],
    source_snapshot_id: str,
) -> None:
    command_ids = [command.crane_id for command in commands]
    state_ids = [state.crane_id for state in crane_states]
    config_ids = [config.crane_id for config in crane_configs]
    if len(command_ids) != len(set(command_ids)):
        raise MechanicalSafetyError("duplicate command crane_id", field_path="commands")
    if set(command_ids) != set(state_ids) or set(command_ids) != set(config_ids):
        raise MechanicalSafetyError(
            "commands, states, and configs must contain the same crane ids",
            field_path="crane_id",
        )
    if any(command.source_snapshot_id != source_snapshot_id for command in commands):
        raise MechanicalSafetyError(
            "command snapshot id mismatch",
            error_code=SAFETY_E_SNAPSHOT_MISMATCH,
            field_path="source_snapshot_id",
        )
