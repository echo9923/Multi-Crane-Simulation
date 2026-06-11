from __future__ import annotations

import math
from typing import Optional

from backend.app.schemas.control import ControlTarget
from backend.app.schemas.crane import CraneConfig
from backend.app.schemas.observation import (
    AxisCommand,
    JoystickCommandSummary,
    LeftJoystickCommand,
    RightJoystickCommand,
    SelfStateSummary,
)
from backend.app.schemas.state import CraneState


class ObservationBuildError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str = "OBSERVATION_E_INVALID_STATE",
        crane_id: Optional[str] = None,
        field_path: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.category = "episode_failed"
        self.episode_status = "failed_invalid_state"
        self.crane_id = crane_id
        self.field_path = field_path


def build_self_state_summary(
    *,
    state: CraneState,
    crane_config: CraneConfig,
    current_command: Optional[ControlTarget],
    distance_precision_m: float,
) -> SelfStateSummary:
    if state.crane_id != crane_config.crane_id:
        raise ObservationBuildError(
            "state crane_id must match crane_config crane_id",
            crane_id=state.crane_id,
            field_path="crane_id",
        )
    if current_command is not None and current_command.crane_id != state.crane_id:
        raise ObservationBuildError(
            "current_command crane_id must match state crane_id",
            crane_id=state.crane_id,
            field_path="current_command.crane_id",
        )

    return SelfStateSummary(
        slew_angle_deg=round(math.degrees(state.theta_rad), 1),
        slew_motion=_slew_motion(state.theta_dot_rad_s),
        trolley_r_m=_round_to_precision(state.trolley_r_m, distance_precision_m),
        hook_h_m=_round_to_precision(state.hook_h_m, distance_precision_m),
        load_attached=state.load_attached,
        load_type=state.load_type,
        load_weight_t=_round_to_precision(state.load_weight_t, 0.1),
        current_command=_command_summary(current_command),
    )


def _command_summary(current_command: Optional[ControlTarget]) -> JoystickCommandSummary:
    if current_command is None:
        return JoystickCommandSummary(
            left_joystick=LeftJoystickCommand(
                slew=AxisCommand(direction="neutral", gear=0),
                trolley=AxisCommand(direction="neutral", gear=0),
            ),
            right_joystick=RightJoystickCommand(
                hoist=AxisCommand(direction="neutral", gear=0)
            ),
            deadman_pressed=True,
            emergency_stop=False,
            hold_position=False,
        )

    return JoystickCommandSummary(
        left_joystick=LeftJoystickCommand(
            slew=AxisCommand(
                direction=_axis_direction(
                    current_command.target_slew_velocity_rad_s,
                    positive="left",
                    negative="right",
                ),
                gear=_gear_for_velocity(current_command.target_slew_velocity_rad_s),
            ),
            trolley=AxisCommand(
                direction=_axis_direction(
                    current_command.target_trolley_velocity_m_s,
                    positive="out",
                    negative="in",
                ),
                gear=_gear_for_velocity(current_command.target_trolley_velocity_m_s),
            ),
        ),
        right_joystick=RightJoystickCommand(
            hoist=AxisCommand(
                direction=_axis_direction(
                    current_command.target_hoist_velocity_m_s,
                    positive="up",
                    negative="down",
                ),
                gear=_gear_for_velocity(current_command.target_hoist_velocity_m_s),
            )
        ),
        deadman_pressed=not current_command.emergency_stop,
        emergency_stop=current_command.emergency_stop,
        hold_position=current_command.hold_position,
    )


def _slew_motion(velocity_rad_s: float) -> str:
    direction = _axis_direction(velocity_rad_s, positive="slow_left", negative="slow_right")
    return "hold" if direction == "neutral" else direction


def _axis_direction(value: float, *, positive: str, negative: str) -> str:
    if abs(value) < 1e-9:
        return "neutral"
    return positive if value > 0 else negative


def _gear_for_velocity(value: float) -> int:
    if abs(value) < 1e-9:
        return 0
    return 1


def _round_to_precision(value: float, precision: float) -> float:
    if precision <= 0 or not math.isfinite(precision):
        raise ObservationBuildError(
            "distance_precision_m must be finite and positive",
            field_path="distance_precision_m",
        )
    if not math.isfinite(value):
        raise ObservationBuildError("observation value must be finite")
    return round(value / precision) * precision

