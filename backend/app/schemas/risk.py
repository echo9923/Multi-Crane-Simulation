from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.schemas.enums import ForbiddenZonePolicyMode, SafetyMode
from backend.app.schemas.observation import OnlineRiskHint

SAFETY_SCHEMA_VERSION = "1.0"
RISK_SCHEMA_VERSION = "1.0"

SAFETY_E_INVALID_STATE = "SAFETY_E_INVALID_STATE"
SAFETY_E_SNAPSHOT_MISMATCH = "SAFETY_E_SNAPSHOT_MISMATCH"
SAFETY_E_DUPLICATE_CRANE = "SAFETY_E_DUPLICATE_CRANE"
SAFETY_E_UNSUPPORTED_ZONE = "SAFETY_E_UNSUPPORTED_ZONE"
RISK_E_FUTURE_TRUTH_FORBIDDEN = "RISK_E_FUTURE_TRUTH_FORBIDDEN"
RISK_E_MISSING_PAIR_INPUT = "RISK_E_MISSING_PAIR_INPUT"
COLLISION_E_GEOMETRY_OVERLAP = "COLLISION_E_GEOMETRY_OVERLAP"

RiskLevel = Literal["safe", "low", "medium", "high", "near_miss", "collision"]
RiskObjectType = Literal["jib", "jib_tip", "hook", "load", "cable", "unknown"]


class SafetyBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class RiskBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SafetyEvent(SafetyBaseModel):
    schema_version: str = SAFETY_SCHEMA_VERSION
    event_id: str
    event_type: str
    time_s: float = Field(ge=0)
    crane_id: Optional[str] = None
    pair_id: Optional[str] = None
    reason: str
    details: Dict[str, Any] = Field(default_factory=dict)


class MechanicalLimitResult(SafetyBaseModel):
    schema_version: str = SAFETY_SCHEMA_VERSION
    crane_id: str
    modified: bool
    applied_limits: List[str] = Field(default_factory=list)
    blocked_axes: List[str] = Field(default_factory=list)
    clamped_axes: List[str] = Field(default_factory=list)
    events: List[SafetyEvent] = Field(default_factory=list)


class ForbiddenZoneResult(SafetyBaseModel):
    schema_version: str = SAFETY_SCHEMA_VERSION
    crane_id: str
    policy_mode: ForbiddenZonePolicyMode
    violation_detected: bool
    blocked: bool
    zone_ids: List[str] = Field(default_factory=list)
    events: List[SafetyEvent] = Field(default_factory=list)


class InterventionRecord(SafetyBaseModel):
    schema_version: str = SAFETY_SCHEMA_VERSION
    intervention_id: str
    crane_id: str
    safety_mode: SafetyMode
    risk_level: RiskLevel
    action: Literal[
        "none",
        "ignored_risk_hint",
        "limit_speed_on_high_risk",
        "force_stop_on_high_risk",
    ]
    modified: bool
    reason: str
    pair_ids: List[str] = Field(default_factory=list)


class RiskPairResult(RiskBaseModel):
    schema_version: str = RISK_SCHEMA_VERSION
    pair_id: str
    crane_id_a: str
    crane_id_b: str
    time_s: float = Field(ge=0)
    d_min_online_m: float = Field(ge=0)
    d_hat_min_m: float = Field(ge=0)
    ttc_hat_s: Optional[float] = Field(default=None, ge=0)
    d_safe_effective_m: float = Field(gt=0)
    base_threshold_m: float = Field(gt=0)
    wind_extra_m: float = Field(ge=0)
    risk_level: RiskLevel
    nearest_object_a: RiskObjectType
    nearest_object_b: RiskObjectType
    relative_motion: Literal["opening", "stable", "closing", "unknown"]
    used_future_truth: bool = False
    confidence: float = Field(ge=0, le=1)
    reasons: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def reject_future_truth(self) -> "RiskPairResult":
        if self.used_future_truth:
            raise ValueError(RISK_E_FUTURE_TRUTH_FORBIDDEN)
        return self


class OnlineRisk(RiskBaseModel):
    schema_version: str = RISK_SCHEMA_VERSION
    risk_id: str
    source_snapshot_id: str
    time_s: float = Field(ge=0)
    pairs: List[RiskPairResult]
    global_risk_level: RiskLevel
    nearest_pair_id: Optional[str] = None
    nearest_neighbor_by_crane: Dict[str, Optional[str]] = Field(default_factory=dict)
    hint_by_crane: Dict[str, OnlineRiskHint] = Field(default_factory=dict)


class CollisionEvent(SafetyBaseModel):
    schema_version: str = SAFETY_SCHEMA_VERSION
    event_id: str
    source_snapshot_id: str
    time_s: float = Field(ge=0)
    crane_id_a: str
    crane_id_b: str
    object_a: RiskObjectType
    object_b: RiskObjectType
    distance_m: float = Field(ge=0)
    episode_status: Literal["failed_collision"] = "failed_collision"
    reason: str


class SafetyPipelineResult(SafetyBaseModel):
    schema_version: str = SAFETY_SCHEMA_VERSION
    source_snapshot_id: str
    time_s: float = Field(ge=0)
    executed_commands: List[Any]
    online_risk: OnlineRisk
    collision: Optional[CollisionEvent] = None
    episode_status: Literal[
        "running", "failed_collision", "failed_invalid_state"
    ] = "running"
    events: List[SafetyEvent] = Field(default_factory=list)
