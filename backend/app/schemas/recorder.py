from __future__ import annotations

from typing import Any, ClassVar, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError

RECORDER_SCHEMA_VERSION = "1.0"

MVP_EVENT_TYPES = {
    "risk_entered",
    "near_miss",
    "risk_resolved",
    "collision",
    "ignored_risk_hint",
    "emergency_stop_triggered",
    "horn_event",
    "intervention_applied",
    "moment_limit",
    "overload_prevented",
    "forbidden_zone_violation",
    "overlap_zone_entered",
    "overlap_zone_exited",
    "overlap_zone_shared",
    "overlap_task_conflict",
    "task_started",
    "task_completed",
    "deadline_missed",
    "attach_failed",
    "release_failed",
    "attach_request_rejected",
    "release_request_rejected",
    "invalid_task_action",
    "llm_timeout",
    "llm_invalid_output",
    "idle_unnecessary_motion",
}


class RecorderBaseModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        validate_default=True,
        arbitrary_types_allowed=True,
    )


class DataExportWarning(RecorderBaseModel):
    schema_version: str = RECORDER_SCHEMA_VERSION
    warning_id: str
    episode_id: Optional[str] = None
    frame: Optional[int] = Field(default=None, ge=0)
    time_s: Optional[float] = Field(default=None, ge=0)
    file_name: Optional[str] = None
    field_path: Optional[str] = None
    warning_type: Literal[
        "nan_to_null",
        "inf_to_null",
        "schema_nullable",
        "write_retry",
    ]
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)


class SimFrameCrane(RecorderBaseModel):
    schema_version: str = RECORDER_SCHEMA_VERSION
    crane_id: str
    base: Tuple[float, float, float]
    root: Tuple[float, float, float]
    tip: Tuple[float, float, float]
    hook: Tuple[float, float, float]
    theta_rad: float
    trolley_r_m: float
    hook_h_m: float
    load_attached: bool
    load_type: Optional[str] = None
    load_size_m: Optional[Tuple[float, float, float]] = None
    task_id: Optional[str] = None
    task_stage: str
    pickup_zone_id: Optional[str] = None
    dropoff_zone_id: Optional[str] = None
    operator_profile: Optional[str] = None
    current_command: Optional[Dict[str, Any]] = None


class SimFramePair(RecorderBaseModel):
    schema_version: str = RECORDER_SCHEMA_VERSION
    crane_i: str
    crane_j: str
    distance_min_raw_now_m: Optional[float] = None
    clearance_min_now_m: Optional[float] = None
    risk_level_now: Optional[str] = None


class SimFrameWeather(RecorderBaseModel):
    schema_version: str = RECORDER_SCHEMA_VERSION
    wind_speed_m_s: float
    wind_gust_m_s: Optional[float] = None
    wind_direction_deg: Optional[float] = None
    visibility: str
    rain_level: Optional[str] = None
    fog_level: Optional[str] = None


class OfflineFrameLabels(RecorderBaseModel):
    schema_version: str = RECORDER_SCHEMA_VERSION
    pair_labels: List[Dict[str, Any]] = Field(default_factory=list)


class SimFrame(RecorderBaseModel):
    type: Literal["sim_frame"] = "sim_frame"
    schema_version: str = RECORDER_SCHEMA_VERSION
    episode_id: str
    scenario_id: Optional[str] = None
    frame: int = Field(ge=0)
    time_s: float = Field(ge=0)
    episode_status: str
    cranes: List[SimFrameCrane]
    pairs: List[SimFramePair] = Field(default_factory=list)
    tasks: List[Dict[str, Any]] = Field(default_factory=list)
    weather: SimFrameWeather
    events: List[Dict[str, Any]] = Field(default_factory=list)
    offline_labels: Optional[OfflineFrameLabels] = None

    @classmethod
    def realtime(cls, **data: Any) -> "SimFrame":
        if data.get("offline_labels") is not None:
            try:
                cls.model_validate(
                    dict(data, realtime_offline_labels_forbidden=True)
                )
            except ValidationError as exc:
                raise exc
        return cls.model_validate(data)


class TrajectoryRow(RecorderBaseModel):
    schema_version: str = RECORDER_SCHEMA_VERSION
    episode_id: str
    scenario_id: Optional[str] = None
    frame: int = Field(ge=0)
    time_s: float = Field(ge=0)
    crane_id: str
    base_x: Optional[float] = None
    base_y: Optional[float] = None
    base_z: Optional[float] = None
    mast_height_m: Optional[float] = None
    jib_length_m: Optional[float] = None
    theta_rad: float
    theta_sin: float
    theta_cos: float
    theta_dot_rad_s: float
    theta_ddot_rad_s2: float
    trolley_r_m: float
    trolley_v_m_s: float
    hook_h_m: float
    hoist_v_m_s: float
    root_x: float
    root_y: float
    root_z: float
    tip_x: float
    tip_y: float
    tip_z: float
    hook_x: float
    hook_y: float
    hook_z: float
    load_attached: bool
    load_type: Optional[str] = None
    load_weight_t: Optional[float] = None
    load_size_x_m: Optional[float] = None
    load_size_y_m: Optional[float] = None
    load_size_z_m: Optional[float] = None
    task_id: Optional[str] = None
    task_stage: str
    pickup_zone_id: Optional[str] = None
    dropoff_zone_id: Optional[str] = None
    operator_mode: Optional[str] = None
    operator_profile: Optional[str] = None
    executed_slew_direction: Optional[str] = None
    executed_slew_gear: Optional[int] = None
    executed_trolley_direction: Optional[str] = None
    executed_trolley_gear: Optional[int] = None
    executed_hoist_direction: Optional[str] = None
    executed_hoist_gear: Optional[int] = None
    executed_deadman_pressed: Optional[bool] = None
    executed_emergency_stop: Optional[bool] = None
    executed_task_action: Optional[str] = None
    wind_speed_m_s: Optional[float] = None
    wind_gust_m_s: Optional[float] = None
    wind_direction_deg: Optional[float] = None
    visibility_level: Optional[str] = None


class PairRiskRow(RecorderBaseModel):
    schema_version: str = RECORDER_SCHEMA_VERSION
    episode_id: str
    scenario_id: Optional[str] = None
    frame: int = Field(ge=0)
    time_s: float = Field(ge=0)
    crane_i: str
    crane_j: str
    distance_min_raw_now_m: Optional[float] = None
    clearance_min_now_m: Optional[float] = None
    distance_jib_jib_raw_now_m: Optional[float] = None
    clearance_jib_jib_now_m: Optional[float] = None
    distance_jib_i_hook_j_raw_now_m: Optional[float] = None
    clearance_jib_i_hook_j_now_m: Optional[float] = None
    distance_jib_j_hook_i_raw_now_m: Optional[float] = None
    clearance_jib_j_hook_i_now_m: Optional[float] = None
    distance_hook_hook_raw_now_m: Optional[float] = None
    clearance_hook_hook_now_m: Optional[float] = None
    min_clearance_future_5s_m: Optional[float] = None
    min_clearance_future_10s_m: Optional[float] = None
    min_clearance_future_15s_m: Optional[float] = None
    ttc_5s_s: Optional[float] = None
    ttc_10s_s: Optional[float] = None
    ttc_15s_s: Optional[float] = None
    risk_level_now: Optional[str] = None
    risk_level_5s: Optional[str] = None
    risk_level_10s: Optional[str] = None
    risk_level_15s: Optional[str] = None
    collision_label_5s: Optional[int] = Field(default=None, ge=0, le=1)
    collision_label_10s: Optional[int] = Field(default=None, ge=0, le=1)
    collision_label_15s: Optional[int] = Field(default=None, ge=0, le=1)


class GraphEdgeRow(RecorderBaseModel):
    schema_version: str = RECORDER_SCHEMA_VERSION
    episode_id: str
    frame: int = Field(ge=0)
    time_s: float = Field(ge=0)
    src_crane_id: str
    dst_crane_id: str
    edge_distance_m: Optional[float] = None
    edge_overlap_ratio: Optional[float] = Field(default=None, ge=0, le=1)
    edge_delta_height_m: Optional[float] = None
    edge_delta_theta_rad: Optional[float] = None
    edge_delta_theta_dot_rad_s: Optional[float] = None
    edge_ttc_s: Optional[float] = None
    edge_risk_level: Optional[str] = None
    edge_weight_physics_prior: Optional[float] = None


class TaskParquetRow(RecorderBaseModel):
    schema_version: str = RECORDER_SCHEMA_VERSION
    episode_id: str
    scenario_id: Optional[str] = None
    task_id: str
    crane_id: str
    task_type: str
    status: str
    failure_reason: Optional[str] = None
    pickup_x: float
    pickup_y: float
    pickup_z: float
    dropoff_x: float
    dropoff_y: float
    dropoff_z: float
    pickup_surface_z_m: Optional[float] = None
    dropoff_surface_z_m: Optional[float] = None
    pickup_hook_target_z_m: Optional[float] = None
    dropoff_hook_target_z_m: Optional[float] = None
    pickup_floor_id: Optional[str] = None
    dropoff_floor_id: Optional[str] = None
    pickup_building_id: Optional[str] = None
    dropoff_building_id: Optional[str] = None
    pickup_zone_id: str
    dropoff_zone_id: str
    load_type: str
    load_weight_t: float
    load_size_x_m: float
    load_size_y_m: float
    load_size_z_m: float
    planned_start_s: Optional[float] = None
    actual_start_s: Optional[float] = None
    completed_time_s: Optional[float] = None
    deadline_s: Optional[float] = None
    deadline_missed: bool
    overtime_s: float = Field(ge=0)


class WeatherParquetRow(RecorderBaseModel):
    schema_version: str = RECORDER_SCHEMA_VERSION
    episode_id: str
    scenario_id: Optional[str] = None
    frame: int = Field(ge=0)
    time_s: float = Field(ge=0)
    wind_speed_m_s: float
    wind_gust_m_s: float
    wind_direction_deg: float
    visibility_level: str
    rain_level: str


class ObservationLogEntry(RecorderBaseModel):
    schema_version: str = RECORDER_SCHEMA_VERSION
    observation_id: str
    episode_id: str
    time_s: float = Field(ge=0)
    crane_id: str
    risk_prompt_mode: str
    observation: Dict[str, Any]
    source_snapshot_id: str


class DecisionLogEntry(RecorderBaseModel):
    schema_version: str = RECORDER_SCHEMA_VERSION
    episode_id: str
    time_s: float = Field(ge=0)
    crane_id: str
    provider: str
    model: str
    call_record: Dict[str, Any]


class CommandLogEntry(RecorderBaseModel):
    schema_version: str = RECORDER_SCHEMA_VERSION
    episode_id: str
    time_s: float = Field(ge=0)
    decision_index: Optional[int] = Field(default=None, ge=0)
    crane_id: str
    operator_id: Optional[str] = None
    operator_profile: Optional[str] = None
    operator_mode: Optional[str] = None
    observation_id: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    raw_llm_response: Optional[Any] = None
    parsed_command: Optional[Dict[str, Any]] = None
    executed_command: Optional[Dict[str, Any]] = None
    modified_by_intervention: bool = False
    modified_by_mechanical_safety: bool = False
    intervention_reason: Optional[str] = None
    mechanical_safety_reason: Optional[str] = None
    latency_ms: Optional[float] = Field(default=None, ge=0)
    token_usage: Optional[Dict[str, Any]] = None
    retry_count: int = Field(default=0, ge=0)
    validation_errors: List[Any] = Field(default_factory=list)
    cache_hit: bool = False
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    attention_target: Optional[str] = None
    reason: Optional[str] = None


class InterventionLogEntry(RecorderBaseModel):
    schema_version: str = RECORDER_SCHEMA_VERSION
    episode_id: str
    time_s: float = Field(ge=0)
    intervention_id: str
    crane_id: str
    safety_mode: Optional[str] = None
    risk_level: Optional[str] = None
    action: str
    modified: bool
    reason: str
    pair_ids: List[str] = Field(default_factory=list)


class EventLogEntry(RecorderBaseModel):
    schema_version: str = RECORDER_SCHEMA_VERSION
    event_id: str
    event_type: str
    episode_id: str
    scenario_id: Optional[str] = None
    frame: int = Field(ge=0)
    time_s: float = Field(ge=0)
    crane_ids: List[str] = Field(default_factory=list)
    risk_level: Optional[str] = None
    distance_min_raw_now_m: Optional[float] = None
    clearance_min_now_m: Optional[float] = None
    details: Dict[str, Any] = Field(default_factory=dict)

    supported_mvp_event_types: ClassVar[set] = MVP_EVENT_TYPES


class EpisodeManifest(RecorderBaseModel):
    schema_version: str = RECORDER_SCHEMA_VERSION
    episode_id: str
    scenario_id: Optional[str] = None
    episode_status: str
    frame_count: int = Field(ge=0)
    dt: float = Field(gt=0)
    coordinate_system: str = "ENU"
    cranes: List[Dict[str, Any]] = Field(default_factory=list)
    site: Dict[str, Any] = Field(default_factory=dict)
    material_zones: List[Dict[str, Any]] = Field(default_factory=list)
    work_zones: List[Dict[str, Any]] = Field(default_factory=list)
    forbidden_zones: List[Dict[str, Any]] = Field(default_factory=list)
    overlap_zones: List[Dict[str, Any]] = Field(default_factory=list)
    offline_labels_available: bool = False


class EpisodeSummary(RecorderBaseModel):
    schema_version: str = RECORDER_SCHEMA_VERSION
    episode_id: str
    scenario_id: Optional[str] = None
    episode_status: str
    duration_s: float = Field(ge=0)
    num_cranes: int = Field(ge=0)
    num_tasks_total: int = Field(ge=0)
    num_tasks_completed: int = Field(ge=0)
    num_tasks_failed: int = Field(ge=0)
    task_completion_rate: float = Field(ge=0, le=1)
    mean_task_duration_s: Optional[float] = Field(default=None, ge=0)
    deadline_missed_count: int = Field(ge=0)
    overtime_mean_s: float = Field(ge=0)
    risk_frame_ratio_by_level: Dict[str, float]
    near_miss_count: int = Field(ge=0)
    collision_count: int = Field(ge=0)
    min_clearance_over_episode: Optional[float] = None
    high_risk_duration_s: float = Field(ge=0)
    num_llm_calls: int = Field(ge=0)
    llm_invalid_output_count: int = Field(ge=0)
    llm_timeout_count: int = Field(ge=0)
    mean_latency_ms: Optional[float] = Field(default=None, ge=0)
    cache_hit_count: int = Field(ge=0)
    operator_profile_distribution: Dict[str, int]
    ignored_risk_hint_count: int = Field(ge=0)
    emergency_stop_count: int = Field(ge=0)
    forbidden_zone_violation_count: int = Field(ge=0)
    overlap_zone_shared_count: int = Field(ge=0)
    has_nan: bool
    has_inf: bool
    max_state_jump: Optional[float] = Field(default=None, ge=0)
    replay_available: bool
    warnings: List[DataExportWarning] = Field(default_factory=list)
