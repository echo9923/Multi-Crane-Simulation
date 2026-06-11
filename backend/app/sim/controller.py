from __future__ import annotations

from typing import Dict, Literal

from backend.app.schemas.command import ExecutedAxisCommand, ExecutedCommand
from backend.app.schemas.control import (
    CTRL_E_INVALID_STATE,
    ControllerConfig,
    ControllerStateError,
)

AxisName = Literal["slew", "trolley", "hoist"]


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
