from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.schemas.enums import ForbiddenZonePolicyMode, SafetyMode
from backend.app.schemas.observation import OnlineRiskHint

SAFETY_SCHEMA_VERSION = "1.0"
RISK_SCHEMA_VERSION = "1.0"
OFFLINE_LABEL_SCHEMA_VERSION = "1.0"

SAFETY_E_INVALID_STATE = "SAFETY_E_INVALID_STATE"
SAFETY_E_SNAPSHOT_MISMATCH = "SAFETY_E_SNAPSHOT_MISMATCH"
SAFETY_E_DUPLICATE_CRANE = "SAFETY_E_DUPLICATE_CRANE"
SAFETY_E_UNSUPPORTED_ZONE = "SAFETY_E_UNSUPPORTED_ZONE"
RISK_E_FUTURE_TRUTH_FORBIDDEN = "RISK_E_FUTURE_TRUTH_FORBIDDEN"
RISK_E_MISSING_PAIR_INPUT = "RISK_E_MISSING_PAIR_INPUT"
COLLISION_E_GEOMETRY_OVERLAP = "COLLISION_E_GEOMETRY_OVERLAP"
OFFLINE_LABEL_E_EMPTY_TRAJECTORY = "OFFLINE_LABEL_E_EMPTY_TRAJECTORY"
OFFLINE_LABEL_E_MISSING_FRAME = "OFFLINE_LABEL_E_MISSING_FRAME"
OFFLINE_LABEL_E_CRANE_ID_MISMATCH = "OFFLINE_LABEL_E_CRANE_ID_MISMATCH"
OFFLINE_LABEL_E_DUPLICATE_TRAJECTORY_ROW = (
    "OFFLINE_LABEL_E_DUPLICATE_TRAJECTORY_ROW"
)
OFFLINE_LABEL_E_INVALID_WINDOW = "OFFLINE_LABEL_E_INVALID_WINDOW"
OFFLINE_LABEL_E_INVALID_GEOMETRY = "OFFLINE_LABEL_E_INVALID_GEOMETRY"
OFFLINE_LABEL_W_LOW_POSITIVE_RATIO = "OFFLINE_LABEL_W_LOW_POSITIVE_RATIO"

RiskLevel = Literal["safe", "low", "medium", "high", "near_miss", "collision"]
RiskObjectType = Literal["jib", "jib_tip", "hook", "load", "cable", "unknown"]

_WINDOW_KEY_RE = re.compile(r"^(0|[1-9]\d*)(?:\.\d+)?s$")


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


class OfflineFutureWindowLabel(RiskBaseModel):
    schema_version: str = OFFLINE_LABEL_SCHEMA_VERSION
    window_s: float = Field(gt=0)
    min_clearance_future_m: float
    ttc_s: Optional[float] = Field(default=None, ge=0)
    risk_level: RiskLevel
    collision_label: int = Field(ge=0, le=1)
    used_future_truth: Literal[True] = True


class OfflinePairGeometryDistance(RiskBaseModel):
    schema_version: str = OFFLINE_LABEL_SCHEMA_VERSION
    distance_min_raw_now_m: float = Field(ge=0)
    clearance_min_now_m: float
    distance_jib_jib_raw_now_m: float = Field(ge=0)
    clearance_jib_jib_now_m: float
    distance_jib_i_hook_j_raw_now_m: float = Field(ge=0)
    clearance_jib_i_hook_j_now_m: float
    distance_jib_j_hook_i_raw_now_m: float = Field(ge=0)
    clearance_jib_j_hook_i_now_m: float
    distance_hook_hook_raw_now_m: float = Field(ge=0)
    clearance_hook_hook_now_m: float
    nearest_object_i: RiskObjectType
    nearest_object_j: RiskObjectType


class OfflineRiskLabel(RiskBaseModel):
    schema_version: str = OFFLINE_LABEL_SCHEMA_VERSION
    episode_id: str
    scenario_id: Optional[str] = None
    frame: int = Field(ge=0)
    time_s: float = Field(ge=0)
    crane_i: str
    crane_j: str
    pair_id: str

    distance_min_raw_now_m: float = Field(ge=0)
    clearance_min_now_m: float
    distance_jib_jib_raw_now_m: float = Field(ge=0)
    clearance_jib_jib_now_m: float
    distance_jib_i_hook_j_raw_now_m: float = Field(ge=0)
    clearance_jib_i_hook_j_now_m: float
    distance_jib_j_hook_i_raw_now_m: float = Field(ge=0)
    clearance_jib_j_hook_i_now_m: float
    distance_hook_hook_raw_now_m: float = Field(ge=0)
    clearance_hook_hook_now_m: float

    min_clearance_future_5s_m: float
    min_clearance_future_10s_m: float
    ttc_5s_s: Optional[float] = Field(default=None, ge=0)
    ttc_10s_s: Optional[float] = Field(default=None, ge=0)
    risk_level_5s: RiskLevel
    risk_level_10s: RiskLevel
    collision_label_5s: int = Field(ge=0, le=1)
    collision_label_10s: int = Field(ge=0, le=1)

    future_window_labels: Dict[str, OfflineFutureWindowLabel] = Field(
        default_factory=dict
    )
    used_future_truth: Literal[True] = True

    @field_validator("future_window_labels")
    @classmethod
    def validate_future_window_keys(
        cls, value: Dict[str, OfflineFutureWindowLabel]
    ) -> Dict[str, OfflineFutureWindowLabel]:
        for key, label in value.items():
            if _window_seconds_from_key(key) is None:
                raise ValueError("future window key must use '<seconds>s' format")
            key_window_s = _window_seconds_from_key(key)
            if key_window_s is None or not math.isclose(
                key_window_s,
                label.window_s,
                rel_tol=0.0,
                abs_tol=1.0e-9,
            ):
                raise ValueError("future window key must match label.window_s")
        return value

    @model_validator(mode="after")
    def validate_offline_label_contract(self) -> "OfflineRiskLabel":
        if self.crane_i >= self.crane_j:
            raise ValueError("crane_i and crane_j must be sorted and distinct")
        if self.pair_id != _pair_id(self.crane_i, self.crane_j):
            raise ValueError("pair_id must match sorted crane ids")
        self._validate_explicit_window(
            "5s",
            min_clearance=self.min_clearance_future_5s_m,
            ttc_s=self.ttc_5s_s,
            risk_level=self.risk_level_5s,
            collision_label=self.collision_label_5s,
        )
        self._validate_explicit_window(
            "10s",
            min_clearance=self.min_clearance_future_10s_m,
            ttc_s=self.ttc_10s_s,
            risk_level=self.risk_level_10s,
            collision_label=self.collision_label_10s,
        )
        return self

    def _validate_explicit_window(
        self,
        key: str,
        *,
        min_clearance: float,
        ttc_s: Optional[float],
        risk_level: RiskLevel,
        collision_label: int,
    ) -> None:
        window = self.future_window_labels.get(key)
        if window is None:
            raise ValueError(f"future_window_labels must include {key}")
        if not math.isclose(
            window.min_clearance_future_m,
            min_clearance,
            rel_tol=0.0,
            abs_tol=1.0e-9,
        ):
            raise ValueError(f"{key} min clearance must match explicit field")
        if not _optional_float_equal(window.ttc_s, ttc_s):
            raise ValueError(f"{key} ttc must match explicit field")
        if window.risk_level != risk_level:
            raise ValueError(f"{key} risk level must match explicit field")
        if window.collision_label != collision_label:
            raise ValueError(f"{key} collision label must match explicit field")


class OfflinePairRiskRecord(RiskBaseModel):
    schema_version: str = OFFLINE_LABEL_SCHEMA_VERSION
    episode_id: str
    scenario_id: Optional[str] = None
    crane_i: str
    crane_j: str
    pair_id: str
    labels: List[OfflineRiskLabel]

    @model_validator(mode="after")
    def validate_pair_record_contract(self) -> "OfflinePairRiskRecord":
        if self.crane_i >= self.crane_j:
            raise ValueError("crane_i and crane_j must be sorted and distinct")
        if self.pair_id != _pair_id(self.crane_i, self.crane_j):
            raise ValueError("pair_id must match sorted crane ids")
        previous_frame: Optional[int] = None
        for label in self.labels:
            if label.episode_id != self.episode_id:
                raise ValueError("label episode_id must match record episode_id")
            if label.scenario_id != self.scenario_id:
                raise ValueError("label scenario_id must match record scenario_id")
            if label.crane_i != self.crane_i or label.crane_j != self.crane_j:
                raise ValueError("label crane pair must match record crane pair")
            if label.pair_id != self.pair_id:
                raise ValueError("label pair_id must match record pair_id")
            if previous_frame is not None and label.frame < previous_frame:
                raise ValueError("labels must be sorted by frame")
            previous_frame = label.frame
        return self


class OfflineRiskAggregate(RiskBaseModel):
    schema_version: str = OFFLINE_LABEL_SCHEMA_VERSION
    group_by: Literal["global", "episode", "scenario", "crane_pair"]
    group_key: str
    sample_count: int = Field(ge=0)
    positive_count_5s: int = Field(ge=0)
    positive_ratio_5s: float = Field(ge=0, le=1)
    positive_count_10s: int = Field(ge=0)
    positive_ratio_10s: float = Field(ge=0, le=1)
    risk_level_counts_5s: Dict[RiskLevel, int] = Field(default_factory=dict)
    risk_level_counts_10s: Dict[RiskLevel, int] = Field(default_factory=dict)

    @field_validator("risk_level_counts_5s", "risk_level_counts_10s")
    @classmethod
    def validate_risk_level_counts(
        cls, value: Dict[RiskLevel, int]
    ) -> Dict[RiskLevel, int]:
        if any(count < 0 for count in value.values()):
            raise ValueError("risk level counts must be non-negative")
        return value


class OfflineRiskReport(RiskBaseModel):
    schema_version: str = OFFLINE_LABEL_SCHEMA_VERSION
    total_labels: int = Field(ge=0)
    aggregates: List[OfflineRiskAggregate] = Field(default_factory=list)
    warnings: List[Dict[str, Any]] = Field(default_factory=list)


class OfflineLabelError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str,
        category: Literal["dataset_build_error", "dataset_build_warning"] = (
            "dataset_build_error"
        ),
        episode_id: Optional[str] = None,
        frame: Optional[int] = None,
        pair_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.category = category
        self.episode_id = episode_id
        self.frame = frame
        self.pair_id = pair_id
        self.details = details or {}


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


def _pair_id(crane_id_a: str, crane_id_b: str) -> str:
    left, right = sorted([crane_id_a, crane_id_b])
    return f"{left}-{right}"


def _window_seconds_from_key(key: str) -> Optional[float]:
    if _WINDOW_KEY_RE.match(key) is None:
        return None
    return float(key[:-1])


def _optional_float_equal(left: Optional[float], right: Optional[float]) -> bool:
    if left is None or right is None:
        return left is right
    return math.isclose(left, right, rel_tol=0.0, abs_tol=1.0e-9)
