from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

PHYSICS_SCHEMA_VERSION = "1.0"


class StateBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CraneState(StateBaseModel):
    schema_version: str = PHYSICS_SCHEMA_VERSION
    crane_id: str

    theta_rad: float
    theta_dot_rad_s: float = 0.0
    theta_ddot_rad_s2: float = 0.0
    theta_sin: float
    theta_cos: float

    trolley_r_m: float
    trolley_v_m_s: float = 0.0
    hook_h_m: float
    hoist_v_m_s: float = 0.0

    root_position: List[float]
    tip_position: List[float]
    hook_position: List[float]
    cable_length_m: float

    load_position: Optional[List[float]] = None
    swing_angle_rad: float = 0.0
    swing_velocity_rad_s: float = 0.0
    wind_effect_on_swing: Optional[Dict[str, Any]] = None

    load_attached: bool = False
    load_type: Optional[str] = None
    load_weight_t: float = Field(default=0.0, ge=0)
    load_size_m: Optional[List[float]] = None

    task_id: Optional[str] = None
    task_stage: str = "idle"

    @field_validator(
        "root_position",
        "tip_position",
        "hook_position",
        "load_position",
        "load_size_m",
    )
    @classmethod
    def validate_xyz_vector(cls, value: Optional[List[float]]) -> Optional[List[float]]:
        if value is not None and len(value) != 3:
            raise ValueError("3D vectors must contain exactly three values")
        return value
