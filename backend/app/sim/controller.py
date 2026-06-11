from __future__ import annotations

import math
from typing import Dict, Literal, Optional

from backend.app.schemas.command import ExecutedAxisCommand, ExecutedCommand
from backend.app.schemas.control import (
    CTRL_E_INVALID_STATE,
    AxisControlDiagnostic,
    ControlTarget,
    ControllerConfig,
    ControllerDiagnostic,
    ControllerStateError,
)
from backend.app.schemas.crane import CraneModelSpec
from backend.app.schemas.state import CraneState

AxisName = Literal["slew", "trolley", "hoist"]
ControllerMode = Literal[
    "normal",
    "neutral_stop",
    "expired_neutral_stop",
    "deadman_stop",
    "emergency_stop",
    "hold_position",
]


def direction_sign(axis: AxisName, direction: str) -> int:
    signs = {
        "slew": {"left": -1, "neutral": 0, "right": 1},
        "trolley": {"in": -1, "neutral": 0, "out": 1},
        "hoist": {"down": -1, "neutral": 0, "up": 1},
    }
    if axis not in signs:
        raise ControllerStateError(
            f"unknown controller axis: {axis}",
            error_code=CTRL_E_INVALID_STATE,
            field_path="axis",
        )
    if direction not in signs[axis]:
        raise ControllerStateError(
            f"unknown direction for {axis}: {direction}",
            error_code=CTRL_E_INVALID_STATE,
            field_path="direction",
        )
    return signs[axis][direction]


def map_axis_to_desired_velocity(
    *,
    axis: AxisName,
    axis_command: ExecutedAxisCommand,
    controller_config: ControllerConfig,
) -> float:
    sign = direction_sign(axis, axis_command.direction)
    if sign == 0 or axis_command.gear == 0:
        return 0.0
    gear_speeds = _gear_speeds_for_axis(axis, controller_config)
    return sign * gear_speeds[axis_command.gear] * axis_command.speed_scale


def map_command_to_desired_velocities(
    *,
    command: ExecutedCommand,
    controller_config: ControllerConfig,
) -> Dict[AxisName, float]:
    return {
        "slew": map_axis_to_desired_velocity(
            axis="slew",
            axis_command=command.left_joystick.slew,
            controller_config=controller_config,
        ),
        "trolley": map_axis_to_desired_velocity(
            axis="trolley",
            axis_command=command.left_joystick.trolley,
            controller_config=controller_config,
        ),
        "hoist": map_axis_to_desired_velocity(
            axis="hoist",
            axis_command=command.right_joystick.hoist,
            controller_config=controller_config,
        ),
    }


def is_command_expired(
    *,
    command: ExecutedCommand,
    now_s: Optional[float],
) -> bool:
    if now_s is None:
        return False
    _validate_finite(now_s, field_path="now_s")
    expires_at = command.time_s + command.command_duration_s
    return now_s > expires_at


def resolve_controller_mode(
    *,
    command: ExecutedCommand,
    now_s: Optional[float],
    hold_position: bool = False,
) -> ControllerMode:
    if command.emergency_stop:
        return "emergency_stop"
    if hold_position:
        return "hold_position"
    if not command.deadman_pressed:
        return "deadman_stop"
    if is_command_expired(command=command, now_s=now_s):
        return "expired_neutral_stop"
    if _is_all_axes_neutral(command):
        return "neutral_stop"
    return "normal"


def compute_stop_mode_target(
    *,
    command: ExecutedCommand,
    state: CraneState,
    model: CraneModelSpec,
    controller_config: ControllerConfig,
    dt_s: float,
    now_s: Optional[float],
    hold_position: bool = False,
) -> tuple[ControlTarget, ControllerDiagnostic]:
    mode = resolve_controller_mode(
        command=command,
        now_s=now_s,
        hold_position=hold_position,
    )
    if mode == "normal":
        raise ControllerStateError(
            "compute_stop_mode_target requires a stop mode",
            error_code=CTRL_E_INVALID_STATE,
            crane_id=command.crane_id,
            field_path="mode",
        )
    targets, diagnostics = smooth_command_velocities(
        desired_velocities={"slew": 0.0, "trolley": 0.0, "hoist": 0.0},
        state=state,
        model=model,
        dt_s=dt_s,
        controller_config=controller_config,
    )
    control_target = ControlTarget(
        crane_id=command.crane_id,
        target_slew_velocity_rad_s=targets["slew"],
        target_trolley_velocity_m_s=targets["trolley"],
        target_hoist_velocity_m_s=targets["hoist"],
        emergency_stop=mode == "emergency_stop",
        hold_position=mode == "hold_position",
        source_command_id=command.command_id,
    )
    diagnostic = _build_controller_diagnostic(
        command=command,
        mode=mode,
        dt_s=dt_s,
        now_s=now_s,
        axes=diagnostics,
    )
    return control_target, diagnostic


def smooth_axis_velocity(
    *,
    axis: AxisName,
    direction: str,
    gear: int,
    speed_scale: float,
    current_velocity: float,
    desired_velocity: float,
    model: CraneModelSpec,
    dt_s: float,
    controller_config: ControllerConfig,
) -> tuple[float, AxisControlDiagnostic]:
    _validate_finite_positive(dt_s, field_path="dt_s")
    _validate_finite(current_velocity, field_path="current_velocity")
    _validate_finite(desired_velocity, field_path="desired_velocity")

    max_velocity = _max_velocity_for_axis(axis, model)
    max_acceleration = _max_acceleration_for_axis(axis, model)
    desired_after_clamp = clamp(desired_velocity, -max_velocity, max_velocity)
    max_delta = max_acceleration * dt_s
    target_velocity = approach(current_velocity, desired_after_clamp, max_delta)
    target_velocity = clamp(target_velocity, -max_velocity, max_velocity)

    speed_clamp_delta = desired_after_clamp - desired_velocity
    acceleration_delta = target_velocity - current_velocity
    target_delta = desired_after_clamp - current_velocity
    acceleration_limited = abs(target_delta) > max_delta
    diagnostic = AxisControlDiagnostic(
        axis=axis,
        direction=direction,
        gear=gear,
        speed_scale=speed_scale,
        current_velocity=current_velocity,
        desired_velocity_before_speed_clamp=desired_velocity,
        desired_velocity_after_speed_clamp=desired_after_clamp,
        target_velocity=target_velocity,
        speed_clamped=desired_after_clamp != desired_velocity,
        acceleration_limited=acceleration_limited,
        speed_clamp_delta=speed_clamp_delta,
        acceleration_delta=acceleration_delta,
        max_velocity_abs=max_velocity,
        max_acceleration_abs=max_acceleration,
    )
    return target_velocity, diagnostic


def smooth_command_velocities(
    *,
    desired_velocities: Dict[AxisName, float],
    state: CraneState,
    model: CraneModelSpec,
    dt_s: float,
    controller_config: ControllerConfig,
) -> tuple[Dict[AxisName, float], list[AxisControlDiagnostic]]:
    targets: Dict[AxisName, float] = {}
    diagnostics: list[AxisControlDiagnostic] = []
    axis_inputs = {
        "slew": ("neutral", 0, state.theta_dot_rad_s),
        "trolley": ("neutral", 0, state.trolley_v_m_s),
        "hoist": ("neutral", 0, state.hoist_v_m_s),
    }
    for axis in ("slew", "trolley", "hoist"):
        direction, gear, current_velocity = axis_inputs[axis]
        target, diagnostic = smooth_axis_velocity(
            axis=axis,
            direction=direction,
            gear=gear,
            speed_scale=1.0,
            current_velocity=current_velocity,
            desired_velocity=desired_velocities[axis],
            model=model,
            dt_s=dt_s,
            controller_config=controller_config,
        )
        targets[axis] = target
        diagnostics.append(diagnostic)
    return targets, diagnostics


def clamp(value: float, low: float, high: float) -> float:
    if low > high:
        raise ControllerStateError(
            "invalid clamp bounds",
            error_code=CTRL_E_INVALID_STATE,
            field_path="clamp",
        )
    return min(max(value, low), high)


def approach(current: float, target: float, max_delta: float) -> float:
    if max_delta < 0 or not math.isfinite(max_delta):
        raise ControllerStateError(
            "max_delta must be finite and non-negative",
            error_code=CTRL_E_INVALID_STATE,
            field_path="max_delta",
        )
    delta = target - current
    if abs(delta) <= max_delta:
        return target
    return current + math.copysign(max_delta, delta)


def _gear_speeds_for_axis(
    axis: AxisName, controller_config: ControllerConfig
) -> Dict[int, float]:
    if axis == "slew":
        return controller_config.slew_gear_speeds_rad_s
    if axis == "trolley":
        return controller_config.trolley_gear_speeds_m_s
    if axis == "hoist":
        return controller_config.hoist_gear_speeds_m_s
    raise ControllerStateError(
        f"unknown controller axis: {axis}",
        error_code=CTRL_E_INVALID_STATE,
        field_path="axis",
    )


def _is_all_axes_neutral(command: ExecutedCommand) -> bool:
    return all(
        axis.direction == "neutral" or axis.gear == 0
        for axis in (
            command.left_joystick.slew,
            command.left_joystick.trolley,
            command.right_joystick.hoist,
        )
    )


def _build_controller_diagnostic(
    *,
    command: ExecutedCommand,
    mode: ControllerMode,
    dt_s: float,
    now_s: Optional[float],
    axes: list[AxisControlDiagnostic],
) -> ControllerDiagnostic:
    return ControllerDiagnostic(
        diagnostic_id=f"CTRL_DIAG_{command.command_id}",
        crane_id=command.crane_id,
        source_command_id=command.command_id,
        mode=mode,
        controller_dt_s=dt_s,
        command_time_s=command.time_s,
        now_s=now_s,
        command_duration_s=command.command_duration_s,
        command_expired=is_command_expired(command=command, now_s=now_s),
        deadman_pressed=command.deadman_pressed,
        emergency_stop_requested=command.emergency_stop,
        axes=axes,
    )


def _max_velocity_for_axis(axis: AxisName, model: CraneModelSpec) -> float:
    if axis == "slew":
        value = model.slew_speed_max_rad_s
    elif axis == "trolley":
        value = model.trolley_speed_max_m_s
    elif axis == "hoist":
        value = model.hoist_speed_max_m_s
    else:
        raise ControllerStateError(
            f"unknown controller axis: {axis}",
            error_code=CTRL_E_INVALID_STATE,
            field_path="axis",
        )
    _validate_finite_positive(value, field_path=f"{axis}.max_velocity")
    return value


def _max_acceleration_for_axis(axis: AxisName, model: CraneModelSpec) -> float:
    if axis == "slew":
        value = model.slew_acc_max_rad_s2
    elif axis == "trolley":
        value = model.trolley_acc_max_m_s2
    elif axis == "hoist":
        value = model.hoist_acc_max_m_s2
    else:
        raise ControllerStateError(
            f"unknown controller axis: {axis}",
            error_code=CTRL_E_INVALID_STATE,
            field_path="axis",
        )
    _validate_finite_positive(value, field_path=f"{axis}.max_acceleration")
    return value


def _validate_finite(value: float, *, field_path: str) -> None:
    if not math.isfinite(value):
        raise ControllerStateError(
            f"{field_path} must be finite",
            error_code=CTRL_E_INVALID_STATE,
            field_path=field_path,
        )


def _validate_finite_positive(value: float, *, field_path: str) -> None:
    _validate_finite(value, field_path=field_path)
    if value <= 0:
        raise ControllerStateError(
            f"{field_path} must be positive",
            error_code=CTRL_E_INVALID_STATE,
            field_path=field_path,
        )
