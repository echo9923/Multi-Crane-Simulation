from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

from backend.app.schemas.state import PHYSICS_SCHEMA_VERSION


class ControlBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ControlTarget(ControlBaseModel):
    schema_version: str = PHYSICS_SCHEMA_VERSION
    crane_id: str
    target_slew_velocity_rad_s: float
    target_trolley_velocity_m_s: float
    target_hoist_velocity_m_s: float
    emergency_stop: bool = False
    hold_position: bool = False
    source_command_id: Optional[str] = None
