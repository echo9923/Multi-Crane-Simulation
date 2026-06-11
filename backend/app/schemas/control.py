from __future__ import annotations

import math
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.schemas.state import PHYSICS_SCHEMA_VERSION

CONTROLLER_SCHEMA_VERSION = "1.0"

DEFAULT_SLEW_GEAR_SPEEDS_RAD_S = {
    0: 0.0,
    1: 0.15,
    2: 0.3,
    3: 0.5,
    4: 0.65,
    5: 0.8,
}
DEFAULT_TROLLEY_GEAR_SPEEDS_M_S = {
    0: 0.0,
    1: 0.08,
    2: 0.15,
    3: 0.3,
    4: 0.4,
    5: 0.5,
}
DEFAULT_HOIST_GEAR_SPEEDS_M_S = {
    0: 0.0,
    1: 0.1,
    2: 0.2,
    3: 0.35,
    4: 0.5,
    5: 0.6,
}

CTRL_E_INVALID_STATE = "CTRL_E_INVALID_STATE"
CTRL_E_IDENTITY_MISMATCH = "CTRL_E_IDENTITY_MISMATCH"
CTRL_E_NUMERIC = "CTRL_E_NUMERIC"


class ControlBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True)


class ControlTarget(ControlBaseModel):
    schema_version: str = PHYSICS_SCHEMA_VERSION
    crane_id: str
    target_slew_velocity_rad_s: float
    target_trolley_velocity_m_s: float
    target_hoist_velocity_m_s: float
    emergency_stop: bool = False
    hold_position: bool = False
    source_command_id: Optional[str] = None


class ControllerConfig(ControlBaseModel):
    schema_version: str = CONTROLLER_SCHEMA_VERSION
    controller_hz: float = Field(gt=0)
    slew_gear_speeds_rad_s: Dict[int, float] = Field(
        default_factory=lambda: dict(DEFAULT_SLEW_GEAR_SPEEDS_RAD_S)
    )
    trolley_gear_speeds_m_s: Dict[int, float] = Field(
        default_factory=lambda: dict(DEFAULT_TROLLEY_GEAR_SPEEDS_M_S)
    )
    hoist_gear_speeds_m_s: Dict[int, float] = Field(
        default_factory=lambda: dict(DEFAULT_HOIST_GEAR_SPEEDS_M_S)
    )
    emergency_deceleration_multiplier: float = Field(default=1.0, gt=0)

    @property
    def controller_dt_s(self) -> float:
        return 1.0 / self.controller_hz

    @field_validator(
        "slew_gear_speeds_rad_s",
        "trolley_gear_speeds_m_s",
        "hoist_gear_speeds_m_s",
    )
    @classmethod
    def validate_gear_table(cls, value: Dict[int, float]) -> Dict[int, float]:
        expected_gears = set(range(6))
        if set(value) != expected_gears:
            raise ValueError("gear table must contain exactly gears 0..5")
        previous = value[0]
        if previous != 0.0:
            raise ValueError("gear 0 speed must be 0")
        for gear in range(6):
            speed = value[gear]
            if not math.isfinite(speed):
                raise ValueError("gear speeds must be finite")
            if speed < 0:
                raise ValueError("gear speeds must be non-negative")
            if gear > 0 and speed < previous:
                raise ValueError("gear speeds must be non-decreasing")
            previous = speed
        return dict(value)


class AxisControlDiagnostic(ControlBaseModel):
    axis: Literal["slew", "trolley", "hoist"]
    direction: str
    gear: int = Field(ge=0, le=5)
    speed_scale: float = Field(ge=0, le=1)
    current_velocity: float
    desired_velocity_before_speed_clamp: float
    desired_velocity_after_speed_clamp: float
    target_velocity: float
    speed_clamped: bool = False
    acceleration_limited: bool = False
    speed_clamp_delta: float = 0.0
    acceleration_delta: float = 0.0
    max_velocity_abs: float = Field(ge=0)
    max_acceleration_abs: float = Field(ge=0)


class ControllerDiagnostic(ControlBaseModel):
    schema_version: str = CONTROLLER_SCHEMA_VERSION
    diagnostic_id: str
    crane_id: str
    source_command_id: Optional[str] = None
    mode: Literal[
        "normal",
        "neutral_stop",
        "expired_neutral_stop",
        "deadman_stop",
        "emergency_stop",
        "hold_position",
    ]
    controller_dt_s: float = Field(gt=0)
    command_time_s: Optional[float] = Field(default=None, ge=0)
    now_s: Optional[float] = Field(default=None, ge=0)
    command_duration_s: Optional[float] = Field(default=None, ge=0)
    command_expired: bool = False
    deadman_pressed: Optional[bool] = None
    emergency_stop_requested: bool = False
    axes: List[AxisControlDiagnostic] = Field(default_factory=list)


class ControllerStateError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str = CTRL_E_INVALID_STATE,
        crane_id: Optional[str] = None,
        field_path: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.category = "episode_failed"
        self.episode_status = "failed_invalid_state"
        self.crane_id = crane_id
        self.field_path = field_path
