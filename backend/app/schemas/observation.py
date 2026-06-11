from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.schemas.enums import (
    FogLevel,
    OperatorProfile,
    RainLevel,
    RiskPromptMode,
    VisibilityLevel,
)

OBSERVATION_SCHEMA_VERSION = "1.0"


class ObservationBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class AxisCommand(ObservationBaseModel):
    direction: str
    gear: int = Field(ge=0, le=5)


class LeftJoystickCommand(ObservationBaseModel):
    slew: AxisCommand
    trolley: AxisCommand


class RightJoystickCommand(ObservationBaseModel):
    hoist: AxisCommand


class JoystickCommandSummary(ObservationBaseModel):
    left_joystick: LeftJoystickCommand
    right_joystick: RightJoystickCommand
    deadman_pressed: bool = True
    emergency_stop: bool = False
    hold_position: bool = False


class SelfStateSummary(ObservationBaseModel):
    schema_version: str = OBSERVATION_SCHEMA_VERSION
    slew_angle_deg: float
    slew_motion: Literal["slow_left", "slow_right", "hold"]
    trolley_r_m: float = Field(ge=0)
    hook_h_m: float
    load_attached: bool
    load_type: Optional[str] = None
    load_weight_t: float = Field(ge=0)
    current_command: JoystickCommandSummary


class TaskObservationSummary(ObservationBaseModel):
    schema_version: str = OBSERVATION_SCHEMA_VERSION
    stage: str
    has_active_task: bool
    type: Optional[str] = None
    priority: Optional[str] = None
    deadline_s: Optional[float] = None
    deadline_missed: bool = False
    overtime_s: float = Field(default=0.0, ge=0)
    pickup_relative_direction: Optional[str] = None
    pickup_distance_m: Optional[float] = Field(default=None, ge=0)
    pickup_height_delta_m: Optional[float] = None
    dropoff_relative_direction: Optional[str] = None
    dropoff_distance_m: Optional[float] = Field(default=None, ge=0)
    dropoff_height_delta_m: Optional[float] = None
    current_target_relative_direction: Optional[str] = None
    current_target_distance_m: Optional[float] = Field(default=None, ge=0)
    current_target_height_delta_m: Optional[float] = None
    load_attached: bool = False
    load_type: Optional[str] = None
    load_weight_t: Optional[float] = Field(default=None, ge=0)
    signal_hint: Optional[str] = None


class VisibleNeighbor(ObservationBaseModel):
    schema_version: str = OBSERVATION_SCHEMA_VERSION
    crane_id: str
    relative_direction: str
    distance_m: float = Field(ge=0)
    distance_level: Literal["near", "medium", "far"]
    hook_visible: bool
    hook_height_m: Optional[float] = None
    jib_motion: Literal["slow_left", "slow_right", "hold"]
    trolley_motion: Literal["in", "out", "hold"]
    hoist_motion: Literal["up", "down", "hold"]
    load_attached: Optional[bool] = None
    task_stage: Optional[str] = None
    in_overlap_zone: bool


class WeatherObservationSummary(ObservationBaseModel):
    schema_version: str = OBSERVATION_SCHEMA_VERSION
    wind_speed_m_s: float = Field(ge=0)
    gust_m_s: float = Field(ge=0)
    wind_direction_deg: float = Field(ge=0, le=360)
    visibility: VisibilityLevel
    rain_level: RainLevel = RainLevel.NONE
    fog_level: FogLevel = FogLevel.NONE
    visibility_confidence: float = Field(ge=0, le=1)


class SafetyHint(ObservationBaseModel):
    schema_version: str = OBSERVATION_SCHEMA_VERSION
    source: Literal["online_risk"]
    risk_level: Literal["low", "medium", "high", "critical"]
    nearest_neighbor: Optional[str] = None
    nearest_object_type: Optional[str] = None
    clearance_now_m: Optional[float] = Field(default=None, ge=0)
    estimated_clearance_next_5s_m: Optional[float] = Field(default=None, ge=0)
    relative_motion: Literal["opening", "stable", "closing", "unknown"]
    confidence: float = Field(ge=0, le=1)
    suggestion: Optional[str] = None


class AvailableActions(ObservationBaseModel):
    schema_version: str = OBSERVATION_SCHEMA_VERSION
    slew_direction: List[Literal["left", "neutral", "right"]] = Field(
        default_factory=lambda: ["left", "neutral", "right"]
    )
    trolley_direction: List[Literal["in", "neutral", "out"]] = Field(
        default_factory=lambda: ["in", "neutral", "out"]
    )
    hoist_direction: List[Literal["up", "neutral", "down"]] = Field(
        default_factory=lambda: ["up", "neutral", "down"]
    )
    gear: List[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5])
    deadman_pressed: List[bool] = Field(default_factory=lambda: [True, False])
    emergency_stop: List[bool] = Field(default_factory=lambda: [True, False])
    task_action: List[Literal["none", "request_attach", "request_release"]] = Field(
        default_factory=lambda: ["none", "request_attach", "request_release"]
    )

    @field_validator("gear")
    @classmethod
    def validate_gear(cls, value: List[int]) -> List[int]:
        if value != [0, 1, 2, 3, 4, 5]:
            raise ValueError("gear must be exactly [0, 1, 2, 3, 4, 5]")
        return value


class RecentDecisionSummary(ObservationBaseModel):
    schema_version: str = OBSERVATION_SCHEMA_VERSION
    time_s: float = Field(ge=0)
    command_summary: str
    result: Optional[str] = None


class MemorySummary(ObservationBaseModel):
    schema_version: str = OBSERVATION_SCHEMA_VERSION
    task_history_summary: Optional[str] = None
    recent_decisions: List[RecentDecisionSummary] = Field(default_factory=list)
    event_summary: List[str] = Field(default_factory=list)


class OnlineRiskHint(SafetyHint):
    pass


class Observation(ObservationBaseModel):
    schema_version: str = OBSERVATION_SCHEMA_VERSION
    observation_id: str
    source_snapshot_id: str
    operator_id: str
    crane_id: str
    time_s: float = Field(ge=0)
    operator_profile: OperatorProfile
    risk_prompt_mode: RiskPromptMode
    task: TaskObservationSummary
    self_state: SelfStateSummary
    visible_neighbors: List[VisibleNeighbor] = Field(default_factory=list)
    weather: WeatherObservationSummary
    safety_hint: Optional[SafetyHint] = None
    available_actions: AvailableActions = Field(default_factory=AvailableActions)
    memory: MemorySummary = Field(default_factory=MemorySummary)
