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
from backend.app.schemas.crane import CraneConfig
from backend.app.schemas.risk import (
    SAFETY_E_INVALID_STATE,
    MechanicalLimitResult,
    SafetyEvent,
)
from backend.app.schemas.state import CraneState

GEAR_TO_SPEED_SCALE = {
    0: 0.0,
    1: 0.2,
    2: 0.4,
    3: 0.6,
    4: 0.8,
    5: 1.0,
}


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
