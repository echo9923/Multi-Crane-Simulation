from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from backend.app.schemas.enums import (
    CoverageTarget,
    ForbiddenZonePolicyMode,
    HeightStrategy,
    LayoutMode,
    LLMFallbackPolicy,
    LLMHistoryMode,
    LLMProviderName,
    LLMSchedulingMode,
    OperatorAssignmentMode,
    OperatorProfile,
    OverlapLevel,
    PriorityLevel,
    RiskPromptMode,
    SafetyMode,
    SlewMode,
    StructuredOutputMode,
    SummarizerMode,
    SummarizerProviderMode,
    TaskAssignmentMode,
    TaskGenerationMode,
    TaskType,
    QueueStartMode,
    RuntimeMode,
    VisibilityLevel,
    WeatherMode,
)


class ConfigBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _validate_numeric_range(values: List[float], field_name: str) -> List[float]:
    if len(values) != 2:
        raise ValueError(f"{field_name} must contain exactly two values")
    if values[0] > values[1]:
        raise ValueError(f"{field_name} minimum must be <= maximum")
    return values


def _validate_distribution(values: Dict[Any, float], field_name: str) -> Dict[Any, float]:
    if any(weight < 0 for weight in values.values()):
        raise ValueError(f"{field_name} weights must be non-negative")
    total = sum(values.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"{field_name} weights must sum to 1.0")
    return values


class BoundaryConfig(ConfigBaseModel):
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float

    @model_validator(mode="after")
    def validate_min_max(self) -> "BoundaryConfig":
        if self.x_min >= self.x_max:
            raise ValueError("x_min must be less than x_max")
        if self.y_min >= self.y_max:
            raise ValueError("y_min must be less than y_max")
        if self.z_min >= self.z_max:
            raise ValueError("z_min must be less than z_max")
        return self


class ZoneConfig(ConfigBaseModel):
    zone_id: str
    type: str
    center: Optional[List[float]] = None
    size: Optional[List[float]] = None
    points: Optional[List[List[float]]] = None
    z_range_m: Optional[List[float]] = None
    load_types: Optional[List[str]] = None
    accepted_load_types: Optional[List[str]] = None

    @field_validator("center", "size")
    @classmethod
    def validate_xyz_vector(cls, value: Optional[List[float]]) -> Optional[List[float]]:
        if value is not None and len(value) != 3:
            raise ValueError("3D vectors must contain exactly three values")
        return value

    @field_validator("z_range_m")
    @classmethod
    def validate_z_range(cls, value: Optional[List[float]]) -> Optional[List[float]]:
        if value is not None:
            return _validate_numeric_range(value, "z_range_m")
        return value


class ForbiddenZonePolicyConfig(ConfigBaseModel):
    mode: ForbiddenZonePolicyMode
    record_violation: bool = True


class SiteConfig(ConfigBaseModel):
    coordinate_system: str
    boundary: BoundaryConfig
    forbidden_zones: List[ZoneConfig] = Field(default_factory=list)
    material_zones: List[ZoneConfig] = Field(default_factory=list)
    work_zones: List[ZoneConfig] = Field(default_factory=list)
    forbidden_zone_policy: ForbiddenZonePolicyConfig


class LoadTypeConfig(ConfigBaseModel):
    display_name: str
    weight_range_t: List[float]
    size_m: List[float]
    shape: str

    @field_validator("weight_range_t")
    @classmethod
    def validate_weight_range(cls, value: List[float]) -> List[float]:
        return _validate_numeric_range(value, "weight_range_t")

    @field_validator("size_m")
    @classmethod
    def validate_size(cls, value: List[float]) -> List[float]:
        if len(value) != 3:
            raise ValueError("size_m must contain exactly three values")
        if any(component <= 0 for component in value):
            raise ValueError("size_m values must be positive")
        return value


class CraneModelLoadChartPointInput(ConfigBaseModel):
    radius_m: float = Field(gt=0)
    capacity_t: float = Field(gt=0)


class CraneModelConfigInput(ConfigBaseModel):
    model_id: str
    jib_length_m: float = Field(gt=0)
    counter_jib_length_m: float = Field(gt=0)
    mast_height_range_m: List[float]
    max_load_t: float = Field(gt=0)
    max_load_radius_m: float = Field(gt=0)
    tip_load_t: float = Field(gt=0)
    rated_moment_t_m: float = Field(gt=0)
    slew_speed_max_deg_s: float = Field(gt=0)
    slew_acc_max_deg_s2: float = Field(gt=0)
    trolley_r_min_m: float = Field(ge=0)
    trolley_r_max_m: float = Field(gt=0)
    trolley_speed_max_m_s: float = Field(gt=0)
    cable_length_min_m: float = Field(ge=0)
    cable_length_max_m: float = Field(gt=0)
    hoist_speed_max_m_s: float = Field(gt=0)
    min_clearance_below_jib_m: float = Field(ge=0)
    load_chart_points: Optional[List[CraneModelLoadChartPointInput]] = None

    @field_validator("mast_height_range_m")
    @classmethod
    def validate_mast_height_range(cls, value: List[float]) -> List[float]:
        return _validate_numeric_range(value, "mast_height_range_m")

    @model_validator(mode="after")
    def validate_min_max_pairs(self) -> "CraneModelConfigInput":
        if self.trolley_r_min_m > self.trolley_r_max_m:
            raise ValueError("trolley_r_min_m must be <= trolley_r_max_m")
        if self.cable_length_min_m > self.cable_length_max_m:
            raise ValueError("cable_length_min_m must be <= cable_length_max_m")
        return self


class LayoutConfig(ConfigBaseModel):
    mode: LayoutMode
    num_cranes: int = Field(gt=0)
    overlap_level: OverlapLevel
    height_strategy: HeightStrategy
    coverage_target: CoverageTarget
    slew_mode_default: SlewMode
    max_sampling_attempts: int = Field(gt=0)


class SlewConfigInput(ConfigBaseModel):
    mode: SlewMode


class ManualCraneLayoutInput(ConfigBaseModel):
    crane_id: str
    model_id: str
    base: List[float]
    mast_height_m: float = Field(gt=0)
    theta_init_deg: float
    slew: SlewConfigInput

    @field_validator("base")
    @classmethod
    def validate_base(cls, value: List[float]) -> List[float]:
        if len(value) != 3:
            raise ValueError("base must contain exactly three values")
        return value


class QueuePolicyConfig(ConfigBaseModel):
    start_mode: QueueStartMode
    initial_start_jitter_s: List[float]
    inter_task_delay_s: List[float]

    @field_validator("initial_start_jitter_s", "inter_task_delay_s")
    @classmethod
    def validate_delay_range(cls, value: List[float]) -> List[float]:
        if any(component < 0 for component in value):
            raise ValueError("delay ranges must be non-negative")
        return _validate_numeric_range(value, "delay range")


class DeadlinePolicyConfig(ConfigBaseModel):
    enabled: bool
    deadline_miss_is_task_failure: bool


class StageTimeoutPolicyConfig(ConfigBaseModel):
    fail_current_task: bool
    terminate_episode: bool


class TaskStateMachineConfig(ConfigBaseModel):
    align_xy_threshold_m: float = Field(gt=0)
    attach_xy_threshold_m: float = Field(gt=0)
    attach_height_threshold_m: float = Field(gt=0)
    release_xy_threshold_m: float = Field(gt=0)
    release_height_threshold_m: float = Field(gt=0)
    safe_transport_height_m: float = Field(gt=0)
    lift_clearance_m: float = Field(gt=0)
    attach_stage_timeout_s: float = Field(gt=0)
    release_stage_timeout_s: float = Field(gt=0)
    task_no_progress_timeout_s: float = Field(gt=0)
    recovery_release_timeout_s: float = Field(gt=0)
    stage_timeout_policy: StageTimeoutPolicyConfig


class ManualTaskInput(ConfigBaseModel):
    task_id: str
    task_type: TaskType
    pickup_zone_id: str
    dropoff_zone_id: str
    load_type: str
    priority: PriorityLevel = PriorityLevel.MEDIUM


class TaskGenerationConfig(ConfigBaseModel):
    assignment_mode: TaskAssignmentMode
    generation_mode: TaskGenerationMode
    num_tasks_per_crane: int = Field(gt=0)
    queue_policy: QueuePolicyConfig
    task_type_distribution: Dict[TaskType, float]
    fallback_pickup_z_m: float = Field(ge=0)
    fallback_dropoff_z_range_m: List[float]
    attach_delay_s: List[float]
    release_delay_s: List[float]
    priority_distribution: Dict[PriorityLevel, float]
    deadline_policy: DeadlinePolicyConfig
    state_machine: TaskStateMachineConfig
    manual_tasks: Optional[List[ManualTaskInput]] = None

    @field_validator("task_type_distribution")
    @classmethod
    def validate_task_distribution(
        cls, value: Dict[TaskType, float]
    ) -> Dict[TaskType, float]:
        return _validate_distribution(value, "task_type_distribution")

    @field_validator("priority_distribution")
    @classmethod
    def validate_priority_distribution(
        cls, value: Dict[PriorityLevel, float]
    ) -> Dict[PriorityLevel, float]:
        return _validate_distribution(value, "priority_distribution")

    @field_validator(
        "fallback_dropoff_z_range_m", "attach_delay_s", "release_delay_s"
    )
    @classmethod
    def validate_ranges(cls, value: List[float]) -> List[float]:
        if any(component < 0 for component in value):
            raise ValueError("ranges must be non-negative")
        return _validate_numeric_range(value, "range")


class WindConfig(ConfigBaseModel):
    base_speed_m_s: float = Field(ge=0)
    gust_speed_m_s: float = Field(ge=0)
    direction_deg: float = Field(ge=0, le=360)


class VisibilityConfig(ConfigBaseModel):
    base_level: VisibilityLevel


class WeatherConfig(ConfigBaseModel):
    mode: WeatherMode
    wind: WindConfig
    visibility: VisibilityConfig


class GeometryEnvelopeConfig(ConfigBaseModel):
    jib_radius_m: float = Field(gt=0)
    hook_radius_m: float = Field(gt=0)
    load_radius_m: float = Field(gt=0)


class RiskThresholdsConfig(ConfigBaseModel):
    low: float = Field(gt=0)
    medium: float = Field(gt=0)
    high: float = Field(gt=0)
    near_miss: float = Field(gt=0)


class WindSafeDistanceFactorConfig(ConfigBaseModel):
    enabled: bool
    extra_clearance_per_10m_s_wind_m: float = Field(ge=0)


class RiskConfig(ConfigBaseModel):
    geometry_envelope: GeometryEnvelopeConfig
    thresholds_m: RiskThresholdsConfig
    ttc_threshold_level: PriorityLevel
    wind_safe_distance_factor: WindSafeDistanceFactorConfig


class ScenarioConfig(ConfigBaseModel):
    schema_version: str
    scenario_id: str
    seed: int
    site: SiteConfig
    load_types: Dict[str, LoadTypeConfig]
    crane_models: List[CraneModelConfigInput]
    layout: LayoutConfig
    cranes: Optional[List[ManualCraneLayoutInput]] = None
    tasks: TaskGenerationConfig
    weather: WeatherConfig
    risk: RiskConfig

    @model_validator(mode="after")
    def validate_manual_cranes(self) -> "ScenarioConfig":
        if self.layout.mode is LayoutMode.MANUAL and not self.cranes:
            raise ValueError("cranes are required when layout.mode is manual")
        return self


class SimConfig(ConfigBaseModel):
    dt: float = Field(gt=0)
    duration_s: float = Field(gt=0)
    min_duration_s: float = Field(ge=0)
    stop_when_all_tasks_done: bool
    completion_cooldown_s: float = Field(ge=0)
    physics_hz: float = Field(gt=0)
    controller_hz: float = Field(gt=0)
    llm_decision_interval_s: float = Field(gt=0)


class RuntimeConfig(ConfigBaseModel):
    mode: RuntimeMode
    replay_mode: bool
    replay_file: Optional[str] = None
    llm_cache_enabled: bool


class OperatorAssignmentConfig(ConfigBaseModel):
    assignment_mode: OperatorAssignmentMode
    profile_distribution: Dict[OperatorProfile, float]

    @field_validator("profile_distribution")
    @classmethod
    def validate_profile_distribution(
        cls, value: Dict[OperatorProfile, float]
    ) -> Dict[OperatorProfile, float]:
        return _validate_distribution(value, "profile_distribution")


class LLMCommandDurationConfig(ConfigBaseModel):
    default_s: float = Field(gt=0)
    min_s: float = Field(gt=0)
    max_s: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_duration_bounds(self) -> "LLMCommandDurationConfig":
        if self.min_s > self.default_s or self.default_s > self.max_s:
            raise ValueError("min_s <= default_s <= max_s is required")
        return self


class LLMSchedulingConfig(ConfigBaseModel):
    mode: LLMSchedulingMode
    stale_command_max_hold_s: float = Field(ge=0)


class StructuredOutputConfig(ConfigBaseModel):
    mode: StructuredOutputMode


class SummarizerTriggerConfig(ConfigBaseModel):
    every_n_decisions: int = Field(gt=0)
    context_over_tokens: int = Field(gt=0)


class SummarizerConfig(ConfigBaseModel):
    mode: SummarizerMode
    provider: SummarizerProviderMode
    fallback: SummarizerMode
    trigger: SummarizerTriggerConfig


class LLMContextConfig(ConfigBaseModel):
    history_mode: LLMHistoryMode
    recent_decisions_full: int = Field(ge=0)
    include_task_history_summary: bool
    include_completed_task_summary: bool
    include_failed_request_history: bool
    include_risk_event_history: bool
    summarizer: SummarizerConfig


class LLMConfig(ConfigBaseModel):
    enabled: bool
    provider: LLMProviderName
    model: str
    base_url: Optional[str] = None
    api_key: Optional[SecretStr] = None
    api_key_env: Optional[str] = None
    temperature: float = Field(ge=0)
    timeout_s: float = Field(gt=0)
    max_retries: int = Field(ge=0)
    max_consecutive_failures: int = Field(gt=0)
    fallback_policy: LLMFallbackPolicy
    command_duration: LLMCommandDurationConfig
    scheduling: LLMSchedulingConfig
    structured_output: StructuredOutputConfig
    context: LLMContextConfig


class OutputConfig(ConfigBaseModel):
    run_root: str = "runs"
    save_visual_frames: bool
    save_parquet: bool
    save_replay: bool


class ExperimentConfig(ConfigBaseModel):
    schema_version: str
    experiment_id: str
    scenario_ref: str
    seed: int
    sim: SimConfig
    risk_prompt_mode: RiskPromptMode
    safety_mode: SafetyMode
    runtime: RuntimeConfig
    operators: OperatorAssignmentConfig
    llm: LLMConfig
    output: OutputConfig


class DatasetSourceConfig(ConfigBaseModel):
    scenario_ref: str
    experiment_template_ref: str
    num_episodes: int = Field(gt=0)


class DatasetHoldoutConfig(ConfigBaseModel):
    unseen_layout: bool
    unseen_num_cranes: bool


class DatasetSplitConfig(ConfigBaseModel):
    strategy: str
    train_ratio: float = Field(ge=0, le=1)
    val_ratio: float = Field(ge=0, le=1)
    test_ratio: float = Field(ge=0, le=1)
    holdout: DatasetHoldoutConfig

    @model_validator(mode="after")
    def validate_split_ratios(self) -> "DatasetSplitConfig":
        total = self.train_ratio + self.val_ratio + self.test_ratio
        if abs(total - 1.0) > 1e-6:
            raise ValueError("train_ratio + val_ratio + test_ratio must equal 1.0")
        return self


class NegativePositiveSamplingConfig(ConfigBaseModel):
    enabled: bool
    max_negative_to_positive_ratio: float = Field(gt=0)


class DatasetWindowConfig(ConfigBaseModel):
    input_steps: int = Field(gt=0)
    pred_steps: int = Field(gt=0)
    stride_steps: int = Field(gt=0)
    risk_label_horizons_s: List[float]
    negative_positive_sampling: NegativePositiveSamplingConfig

    @field_validator("risk_label_horizons_s")
    @classmethod
    def validate_horizons(cls, value: List[float]) -> List[float]:
        if not value:
            raise ValueError("risk_label_horizons_s must not be empty")
        if any(horizon <= 0 for horizon in value):
            raise ValueError("risk_label_horizons_s values must be positive")
        return value


class DatasetExportConfig(ConfigBaseModel):
    format: str
    include_metadata: bool
    write_dataset_summary: bool


class DatasetConfig(ConfigBaseModel):
    schema_version: str
    dataset_id: str
    run_root: str
    sources: List[DatasetSourceConfig]
    split: DatasetSplitConfig
    windows: DatasetWindowConfig
    export: DatasetExportConfig
