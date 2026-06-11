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
    TaskRecoveryPolicy,
    TaskType,
    QueueStartMode,
    RuntimeMode,
    VisibilityLevel,
    RainLevel,
    FogLevel,
    WeatherMode,
    WeatherRuntimeFailurePolicy,
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


class TaskAxisSpeedThresholdConfig(ConfigBaseModel):
    slew_deg_s: float = Field(gt=0)
    trolley_m_s: float = Field(gt=0)
    hoist_m_s: float = Field(gt=0)


class TaskStateMachineConfig(ConfigBaseModel):
    align_xy_threshold_m: float = Field(gt=0)
    attach_xy_threshold_m: float = Field(gt=0)
    attach_height_threshold_m: float = Field(gt=0)
    release_xy_threshold_m: float = Field(gt=0)
    release_height_threshold_m: float = Field(gt=0)
    attach_speed_threshold: TaskAxisSpeedThresholdConfig = Field(
        default_factory=lambda: TaskAxisSpeedThresholdConfig(
            slew_deg_s=0.3,
            trolley_m_s=0.08,
            hoist_m_s=0.05,
        )
    )
    release_speed_threshold: TaskAxisSpeedThresholdConfig = Field(
        default_factory=lambda: TaskAxisSpeedThresholdConfig(
            slew_deg_s=0.3,
            trolley_m_s=0.08,
            hoist_m_s=0.05,
        )
    )
    safe_transport_height_m: float = Field(gt=0)
    lift_clearance_m: float = Field(gt=0)
    attach_stage_timeout_s: float = Field(gt=0)
    release_stage_timeout_s: float = Field(gt=0)
    task_no_progress_timeout_s: float = Field(gt=0)
    recovery_release_timeout_s: float = Field(gt=0)
    no_progress_xy_epsilon_m: float = Field(default=0.25, gt=0)
    stage_timeout_policy: StageTimeoutPolicyConfig


class ManualTaskInput(ConfigBaseModel):
    task_id: str
    task_type: TaskType
    pickup_zone_id: str
    dropoff_zone_id: str
    load_type: str
    priority: PriorityLevel = PriorityLevel.MEDIUM


class TaskRecoveryConfig(ConfigBaseModel):
    enabled: bool = True
    policy: TaskRecoveryPolicy = TaskRecoveryPolicy.ATTEMPT_SAFE_RELEASE
    emergency_drop_zones: List[str] = Field(default_factory=list)


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
    recovery: TaskRecoveryConfig = Field(default_factory=TaskRecoveryConfig)
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
    speed_bounds_m_s: Optional[List[float]] = None
    direction_variability_deg: float = Field(default=0.0, ge=0)
    gust_probability: float = Field(default=0.0, ge=0, le=1)
    gust_duration_s: Optional[List[float]] = None

    @field_validator("speed_bounds_m_s", "gust_duration_s")
    @classmethod
    def validate_optional_ranges(cls, value: Optional[List[float]]) -> Optional[List[float]]:
        if value is None:
            return value
        if any(component < 0 for component in value):
            raise ValueError("WEATHER_E_001 weather range values must be non-negative")
        return _validate_numeric_range(value, "weather range")

    @model_validator(mode="after")
    def validate_gust_not_below_base(self) -> "WindConfig":
        if self.gust_speed_m_s < self.base_speed_m_s:
            raise ValueError("WEATHER_E_001 gust_speed_m_s must be >= base_speed_m_s")
        return self


class VisibilityConfig(ConfigBaseModel):
    base_level: VisibilityLevel
    levels: Optional[Dict[VisibilityLevel, Dict[str, float]]] = None

    @field_validator("base_level", mode="before")
    @classmethod
    def canonicalize_base_level(cls, value: object) -> object:
        if isinstance(value, str):
            return _canonical_visibility_value(value)
        return value

    @field_validator("levels", mode="before")
    @classmethod
    def canonicalize_level_keys(
        cls, value: Optional[Dict[Any, Dict[str, float]]]
    ) -> Optional[Dict[str, Dict[str, float]]]:
        if value is None:
            return value
        return {_canonical_visibility_value(str(key)): item for key, item in value.items()}


class PrecipitationConfig(ConfigBaseModel):
    rain_level: RainLevel = RainLevel.NONE
    fog_level: FogLevel = FogLevel.NONE


class WeatherScheduleSegmentConfig(ConfigBaseModel):
    segment_id: str
    start_s: float = Field(ge=0)
    end_s: Optional[float] = Field(default=None, gt=0)
    wind_speed_m_s: float = Field(ge=0)
    wind_gust_m_s: float = Field(ge=0)
    wind_direction_deg: float = Field(ge=0, le=360)
    visibility_level: VisibilityLevel
    rain_level: RainLevel = RainLevel.NONE
    fog_level: FogLevel = FogLevel.NONE
    transition_s: float = Field(default=0.0, ge=0)

    @field_validator("visibility_level", mode="before")
    @classmethod
    def canonicalize_visibility_level(cls, value: object) -> object:
        if isinstance(value, str):
            return _canonical_visibility_value(value)
        return value

    @model_validator(mode="after")
    def validate_segment(self) -> "WeatherScheduleSegmentConfig":
        if self.end_s is not None and self.end_s <= self.start_s:
            raise ValueError("WEATHER_E_002 schedule segment end_s must be > start_s")
        if self.wind_gust_m_s < self.wind_speed_m_s:
            raise ValueError("WEATHER_E_002 wind_gust_m_s must be >= wind_speed_m_s")
        return self


class WeatherScheduleConfig(ConfigBaseModel):
    segments: List[WeatherScheduleSegmentConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_segments(self) -> "WeatherScheduleConfig":
        if not self.segments:
            return self
        first = self.segments[0]
        if first.start_s != 0:
            raise ValueError("WEATHER_E_002 first schedule segment must start at 0")
        for index, segment in enumerate(self.segments):
            if segment.end_s is None and index != len(self.segments) - 1:
                raise ValueError("WEATHER_E_002 only the last segment may have end_s=null")
            if index == 0:
                continue
            previous = self.segments[index - 1]
            if segment.start_s <= previous.start_s:
                raise ValueError("WEATHER_E_002 schedule segment start_s must increase")
            if previous.end_s is None:
                raise ValueError("WEATHER_E_002 segment after open-ended segment is invalid")
            if segment.start_s != previous.end_s:
                raise ValueError("WEATHER_E_002 schedule segments must be continuous")
        return self


class WeatherRandomConfig(ConfigBaseModel):
    change_interval_s: Optional[List[float]] = None
    smoothing_time_s: Optional[float] = Field(default=None, ge=0)
    wind_speed_range_m_s: Optional[List[float]] = None
    gust_extra_range_m_s: Optional[List[float]] = None
    direction_change_range_deg: Optional[List[float]] = None
    visibility_distribution: Optional[Dict[VisibilityLevel, float]] = None
    rain_distribution: Optional[Dict[RainLevel, float]] = None
    fog_distribution: Optional[Dict[FogLevel, float]] = None

    @field_validator(
        "change_interval_s",
        "wind_speed_range_m_s",
        "gust_extra_range_m_s",
    )
    @classmethod
    def validate_non_negative_ranges(
        cls, value: Optional[List[float]]
    ) -> Optional[List[float]]:
        if value is None:
            return value
        if any(component < 0 for component in value):
            raise ValueError("WEATHER_E_003 random weather ranges must be non-negative")
        return _validate_numeric_range(value, "random weather range")

    @field_validator("direction_change_range_deg")
    @classmethod
    def validate_direction_change_range(
        cls, value: Optional[List[float]]
    ) -> Optional[List[float]]:
        if value is None:
            return value
        return _validate_numeric_range(value, "direction_change_range_deg")

    @field_validator("visibility_distribution", mode="before")
    @classmethod
    def canonicalize_visibility_distribution(
        cls, value: Optional[Dict[Any, float]]
    ) -> Optional[Dict[str, float]]:
        if value is None:
            return value
        return {_canonical_visibility_value(str(key)): weight for key, weight in value.items()}

    @field_validator("visibility_distribution")
    @classmethod
    def validate_visibility_distribution(
        cls, value: Optional[Dict[VisibilityLevel, float]]
    ) -> Optional[Dict[VisibilityLevel, float]]:
        if value is not None:
            return _validate_distribution(value, "WEATHER_E_003 visibility_distribution")
        return value

    @field_validator("rain_distribution")
    @classmethod
    def validate_rain_distribution(
        cls, value: Optional[Dict[RainLevel, float]]
    ) -> Optional[Dict[RainLevel, float]]:
        if value is not None:
            return _validate_distribution(value, "WEATHER_E_003 rain_distribution")
        return value

    @field_validator("fog_distribution")
    @classmethod
    def validate_fog_distribution(
        cls, value: Optional[Dict[FogLevel, float]]
    ) -> Optional[Dict[FogLevel, float]]:
        if value is not None:
            return _validate_distribution(value, "WEATHER_E_003 fog_distribution")
        return value


class WeatherConfig(ConfigBaseModel):
    enabled: bool = True
    mode: WeatherMode
    update_interval_s: Optional[float] = Field(default=None, gt=0)
    runtime_failure_policy: WeatherRuntimeFailurePolicy = (
        WeatherRuntimeFailurePolicy.FAIL_EPISODE
    )
    wind: WindConfig
    visibility: VisibilityConfig
    precipitation: PrecipitationConfig = Field(default_factory=PrecipitationConfig)
    schedule: WeatherScheduleConfig = Field(default_factory=WeatherScheduleConfig)
    random: WeatherRandomConfig = Field(default_factory=WeatherRandomConfig)
    wind_advisory_thresholds_m_s: Optional[Dict[str, float]] = None

    @field_validator("wind_advisory_thresholds_m_s")
    @classmethod
    def validate_wind_advisory_thresholds(
        cls, value: Optional[Dict[str, float]]
    ) -> Optional[Dict[str, float]]:
        if value is None:
            return value
        required = {"caution", "gusty", "strong_wind"}
        if set(value) != required:
            raise ValueError("WEATHER_E_001 wind advisory thresholds are incomplete")
        if any(threshold < 0 for threshold in value.values()):
            raise ValueError("WEATHER_E_001 wind advisory thresholds must be non-negative")
        if not value["caution"] <= value["gusty"] <= value["strong_wind"]:
            raise ValueError("WEATHER_E_001 wind advisory thresholds must be ordered")
        return value


def _canonical_visibility_value(value: str) -> str:
    aliases = {
        "high": "good",
        "medium": "medium",
        "low": "poor",
        "good": "good",
        "poor": "poor",
    }
    try:
        return aliases[value]
    except KeyError as exc:
        raise ValueError(f"WEATHER_E_001 unknown visibility level: {value}") from exc


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
