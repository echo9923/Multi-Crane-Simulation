# Task 01：Recorder Schema

## 任务目标

定义 Module L 的 Pydantic schema，使 `SimFrame`、`EpisodeSummary`、Parquet 行对象和 JSONL 日志对象成为所有 recorder 输出的唯一事实源。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/schemas/recorder.py`。
- 定义 `RECORDER_SCHEMA_VERSION = "1.0"`。
- 定义 `RecorderBaseModel`，使用 `extra="forbid"`、`allow_inf_nan=False`、`validate_default=True`。
- 定义 `SimFrame` 及其 `cranes`、`pairs`、`tasks`、`weather`、`events` 子结构。
- 定义 `EpisodeSummary`，覆盖总方案 L.8 的 25+ 指标。
- 定义 `TrajectoryRow`，对齐 L.2 的 40+ 列，并兼容 `crane_state_to_trajectory_row()` 当前输出的 `frame_index`、`root_x_m` 等命名。
- 定义 `PairRiskRow`，对齐 L.3 的当前距离、5/10/15 秒未来窗口、TTC、risk 和 collision label。
- 定义 `GraphEdgeRow`，对齐 L.4。
- 定义 `TaskParquetRow`、`WeatherParquetRow`。
- 定义 `ObservationLogEntry`、`DecisionLogEntry`、`CommandLogEntry`、`InterventionLogEntry`、`EventLogEntry`。
- 定义 `EpisodeManifest` 和 `DataExportWarning`。
- 明确 `offline_labels` 只允许出现在离线回放 `SimFrame` 的可选扩展中，实时 `SimFrame` 禁止携带。

不做：

- 不写文件。
- 不实现 Parquet/JSONL writer。
- 不计算 summary 指标。
- 不从 `CraneState`、`OnlineRisk` 或 `OfflineRiskLabel` 构造行对象。
- 不改动上游 schema。

## 接口与数据结构（签名级别）

基础对象：

```python
RECORDER_SCHEMA_VERSION = "1.0"

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
    episode_id: str | None = None
    frame: int | None = Field(default=None, ge=0)
    time_s: float | None = Field(default=None, ge=0)
    file_name: str | None = None
    field_path: str | None = None
    warning_type: Literal["nan_to_null", "inf_to_null", "schema_nullable", "write_retry"]
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
```

`SimFrame`：

```python
class SimFrameCrane(RecorderBaseModel):
    schema_version: str = RECORDER_SCHEMA_VERSION
    crane_id: str
    base: tuple[float, float, float]
    root: tuple[float, float, float]
    tip: tuple[float, float, float]
    hook: tuple[float, float, float]
    theta_rad: float
    trolley_r_m: float
    hook_h_m: float
    load_attached: bool
    load_type: str | None = None
    load_size_m: tuple[float, float, float] | None = None
    task_id: str | None = None
    task_stage: str
    pickup_zone_id: str | None = None
    dropoff_zone_id: str | None = None
    operator_profile: str | None = None
    current_command: dict[str, Any] | None = None
```

```python
class SimFramePair(RecorderBaseModel):
    schema_version: str = RECORDER_SCHEMA_VERSION
    crane_i: str
    crane_j: str
    distance_min_raw_now_m: float | None = None
    clearance_min_now_m: float | None = None
    risk_level_now: str | None = None
```

```python
class SimFrameWeather(RecorderBaseModel):
    schema_version: str = RECORDER_SCHEMA_VERSION
    wind_speed_m_s: float
    wind_gust_m_s: float | None = None
    wind_direction_deg: float | None = None
    visibility: str
    rain_level: str | None = None
    fog_level: str | None = None
```

```python
class OfflineFrameLabels(RecorderBaseModel):
    schema_version: str = RECORDER_SCHEMA_VERSION
    pair_labels: list[dict[str, Any]] = Field(default_factory=list)
```

```python
class SimFrame(RecorderBaseModel):
    type: Literal["sim_frame"] = "sim_frame"
    schema_version: str = RECORDER_SCHEMA_VERSION
    episode_id: str
    scenario_id: str | None = None
    frame: int = Field(ge=0)
    time_s: float = Field(ge=0)
    episode_status: str
    cranes: list[SimFrameCrane]
    pairs: list[SimFramePair] = Field(default_factory=list)
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    weather: SimFrameWeather
    events: list[dict[str, Any]] = Field(default_factory=list)
    offline_labels: OfflineFrameLabels | None = None
```

实时 frame 构造器必须提供 `for_realtime: bool` 或等价校验；当 `for_realtime=True` 且 `offline_labels is not None` 时校验失败。

Parquet 行对象：

```python
class TrajectoryRow(RecorderBaseModel):
    schema_version: str = RECORDER_SCHEMA_VERSION
    episode_id: str
    scenario_id: str | None = None
    frame: int = Field(ge=0)
    time_s: float = Field(ge=0)
    crane_id: str
    base_x: float | None = None
    base_y: float | None = None
    base_z: float | None = None
    mast_height_m: float | None = None
    jib_length_m: float | None = None
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
    load_type: str | None = None
    load_weight_t: float | None = None
    load_size_x_m: float | None = None
    load_size_y_m: float | None = None
    load_size_z_m: float | None = None
    task_id: str | None = None
    task_stage: str
    pickup_zone_id: str | None = None
    dropoff_zone_id: str | None = None
    operator_mode: str | None = None
    operator_profile: str | None = None
    executed_slew_direction: str | None = None
    executed_slew_gear: int | None = None
    executed_trolley_direction: str | None = None
    executed_trolley_gear: int | None = None
    executed_hoist_direction: str | None = None
    executed_hoist_gear: int | None = None
    executed_deadman_pressed: bool | None = None
    executed_emergency_stop: bool | None = None
    executed_task_action: str | None = None
    wind_speed_m_s: float | None = None
    wind_gust_m_s: float | None = None
    wind_direction_deg: float | None = None
    visibility_level: str | None = None
```

```python
class PairRiskRow(RecorderBaseModel):
    schema_version: str = RECORDER_SCHEMA_VERSION
    episode_id: str
    scenario_id: str | None = None
    frame: int = Field(ge=0)
    time_s: float = Field(ge=0)
    crane_i: str
    crane_j: str
    distance_min_raw_now_m: float | None = None
    clearance_min_now_m: float | None = None
    distance_jib_jib_raw_now_m: float | None = None
    clearance_jib_jib_now_m: float | None = None
    distance_jib_i_hook_j_raw_now_m: float | None = None
    clearance_jib_i_hook_j_now_m: float | None = None
    distance_jib_j_hook_i_raw_now_m: float | None = None
    clearance_jib_j_hook_i_now_m: float | None = None
    distance_hook_hook_raw_now_m: float | None = None
    clearance_hook_hook_now_m: float | None = None
    min_clearance_future_5s_m: float | None = None
    min_clearance_future_10s_m: float | None = None
    min_clearance_future_15s_m: float | None = None
    ttc_5s_s: float | None = None
    ttc_10s_s: float | None = None
    ttc_15s_s: float | None = None
    risk_level_now: str | None = None
    risk_level_5s: str | None = None
    risk_level_10s: str | None = None
    risk_level_15s: str | None = None
    collision_label_5s: int | None = Field(default=None, ge=0, le=1)
    collision_label_10s: int | None = Field(default=None, ge=0, le=1)
    collision_label_15s: int | None = Field(default=None, ge=0, le=1)
```

```python
class GraphEdgeRow(RecorderBaseModel):
    schema_version: str = RECORDER_SCHEMA_VERSION
    episode_id: str
    frame: int = Field(ge=0)
    time_s: float = Field(ge=0)
    src_crane_id: str
    dst_crane_id: str
    edge_distance_m: float | None = None
    edge_overlap_ratio: float | None = Field(default=None, ge=0, le=1)
    edge_delta_height_m: float | None = None
    edge_delta_theta_rad: float | None = None
    edge_delta_theta_dot_rad_s: float | None = None
    edge_ttc_s: float | None = None
    edge_risk_level: str | None = None
    edge_weight_physics_prior: float | None = None
```

`TaskParquetRow` 和 `WeatherParquetRow` 必须覆盖 L.4.1 最低字段。`ObservationLogEntry`、`CommandLogEntry`、`DecisionLogEntry`、`InterventionLogEntry`、`EventLogEntry` 必须覆盖 L.4.1、L.5、L.6 最低字段。

`EventLogEntry.event_type` 的 MVP 值集合至少包含：

```text
risk_entered
near_miss
risk_resolved
collision
ignored_risk_hint
emergency_stop_triggered
horn_event
intervention_applied
moment_limit
overload_prevented
forbidden_zone_violation
overlap_zone_entered
overlap_zone_exited
overlap_zone_shared
overlap_task_conflict
task_started
task_completed
deadline_missed
attach_failed
release_failed
attach_request_rejected
release_request_rejected
invalid_task_action
llm_timeout
llm_invalid_output
idle_unnecessary_motion
```

`EpisodeSummary` 至少包含：

```python
class EpisodeSummary(RecorderBaseModel):
    schema_version: str = RECORDER_SCHEMA_VERSION
    episode_id: str
    scenario_id: str | None = None
    episode_status: str
    duration_s: float = Field(ge=0)
    num_cranes: int = Field(ge=0)
    num_tasks_total: int = Field(ge=0)
    num_tasks_completed: int = Field(ge=0)
    num_tasks_failed: int = Field(ge=0)
    task_completion_rate: float = Field(ge=0, le=1)
    mean_task_duration_s: float | None = Field(default=None, ge=0)
    deadline_missed_count: int = Field(ge=0)
    overtime_mean_s: float = Field(ge=0)
    risk_frame_ratio_by_level: dict[str, float]
    near_miss_count: int = Field(ge=0)
    collision_count: int = Field(ge=0)
    min_clearance_over_episode: float | None = None
    high_risk_duration_s: float = Field(ge=0)
    num_llm_calls: int = Field(ge=0)
    llm_invalid_output_count: int = Field(ge=0)
    llm_timeout_count: int = Field(ge=0)
    mean_latency_ms: float | None = Field(default=None, ge=0)
    cache_hit_count: int = Field(ge=0)
    operator_profile_distribution: dict[str, int]
    ignored_risk_hint_count: int = Field(ge=0)
    emergency_stop_count: int = Field(ge=0)
    forbidden_zone_violation_count: int = Field(ge=0)
    overlap_zone_shared_count: int = Field(ge=0)
    has_nan: bool
    has_inf: bool
    max_state_jump: float | None = Field(default=None, ge=0)
    replay_available: bool
    warnings: list[DataExportWarning] = Field(default_factory=list)
```

## 前置依赖

- `backend/app/schemas/state.py`、`task.py`、`weather.py`、`command.py`、`risk.py`、`control.py`、`scheduler.py` 已有基础对象。
- `RiskLevel` 当前在 `backend/app/schemas/risk.py` 是 Literal，可在 recorder schema 中用 `str` 降低跨模块耦合，或导入 `RiskLevel` 增强校验；实现阶段二选一并在测试中固定。
- Pydantic v2。

## 验收标准（具体、可测试）

- 所有新增 schema 都有 `schema_version`。
- 所有新增 schema 拒绝 extra 字段。
- 所有新增 schema 拒绝 NaN/Inf。
- `SimFrame` 最小 payload 可序列化为总方案 L.7 的 JSON 形态。
- 实时 `SimFrame` 拒绝 `offline_labels`。
- 离线 `SimFrame` 允许 `offline_labels`，但字段名不得进入 `ObservationLogEntry`。
- `TrajectoryRow` 字段集合覆盖 L.2 的必需列。
- `PairRiskRow` 字段集合覆盖 L.3 的 5/10/15 秒列。
- `GraphEdgeRow` 字段集合覆盖 L.4。
- `TaskParquetRow`、`WeatherParquetRow` 覆盖 L.4.1。
- `CommandLogEntry` 覆盖 L.5 的 raw/parsed/executed、latency、token、retry、cache、validation 字段。
- `EventLogEntry` 支持 25+ MVP event type。
- `EpisodeSummary` 覆盖 L.8 指标，并可 `model_dump(mode="json")`。

## 测试要点（正常 + 边界 + 异常）

- 正常：构造两台塔吊、一个 pair、一个 event 的 `SimFrame`。
- 正常：构造包含 15s offline label 的离线 `SimFrame`。
- 正常：构造完整 `TrajectoryRow`、`PairRiskRow`、`GraphEdgeRow`、`TaskParquetRow`、`WeatherParquetRow`。
- 正常：构造 command/event/observation/decision JSONL entry。
- 边界：nullable numeric 使用 `None`。
- 边界：`scenario_id=None` 合法。
- 异常：extra 字段失败。
- 异常：NaN/Inf 失败。
- 异常：实时 frame 携带 offline labels 失败。
- 防泄漏：静态断言 `ObservationLogEntry` 不含 `offline_label`、`future_min_distance`、`future_ttc` 等字段。

## 依赖关系

Task 01 是 Module L 所有后续任务的前置依赖。它不依赖 Task 02-08。
