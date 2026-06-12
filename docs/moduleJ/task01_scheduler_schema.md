# Task 01：Scheduler Schema

## 任务目标

定义 Module J 的调度层 schema 与状态合同，包括 `WorldSnapshot`、`EpisodeStatus`、`SchedulerConfig`、`CommandStore` 输入输出形状、`EpisodeResult` 和调度错误映射。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/schemas/scheduler.py`。
- 定义 `SCHEDULER_SCHEMA_VERSION`。
- 定义 `EpisodeStatus` 枚举或 string literal 合同。
- 定义 `SchedulerConfig`，从 `ResolvedConfig` / dict / typed config 提取运行所需字段。
- 定义 `WorldSnapshot` Pydantic schema。
- 定义 `CommandStoreState` / `StoredCommand` / `CommandStoreSnapshot` 等可序列化状态对象。
- 定义 `EpisodeResult`、`FrameStepResult`、`TerminalStatusCandidate`、`ReplayValidationConfig` 等调度层返回对象。
- 定义 `SchedulerError` 与最低错误码。
- 所有 J 拥有 schema 使用 `extra="forbid"`，运行态数值拒绝 NaN/Inf。

不做：

- 不实现 `freeze_world_snapshot()`。
- 不实现 `CommandStore` 行为。
- 不实现 frame loop。
- 不调用任何上游模块。
- 不写测试以外的 fixture 数据文件。
- 不把 `RuntimeMode` 扩展出 `offline_wait`；`offline_wait/realtime_stale` 属于 LLM scheduling policy。

## 接口与数据结构（签名级别）

建议 schema：

```python
SCHEDULER_SCHEMA_VERSION = "1.0"

class EpisodeStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    FAILED_COLLISION = "failed_collision"
    FAILED_INVALID_STATE = "failed_invalid_state"
    LLM_FAILED = "llm_failed"
    FAILED_REPLAY_MISMATCH = "failed_replay_mismatch"
    FAILED_RECOVERY_BLOCKED = "failed_recovery_blocked"
    FAILED_RECOVERY_TIMEOUT = "failed_recovery_timeout"
    STOPPED_BY_USER = "stopped_by_user"

class SchedulerConfig(BaseModel):
    schema_version: str = SCHEDULER_SCHEMA_VERSION
    dt_s: float
    duration_s: float
    min_duration_s: float = 0.0
    stop_when_all_tasks_done: bool = True
    completion_cooldown_s: float = 0.0
    controller_hz: float
    llm_decision_interval_s: float
    run_mode: RuntimeMode
    llm_scheduling_mode: LLMSchedulingMode | None = None
    max_consecutive_llm_failures: int | None = None
    realtime_wall_clock: bool = False
    replay: ReplayValidationConfig | None = None

    @classmethod
    def from_config(cls, config: object) -> "SchedulerConfig":
        ...

class ReplayValidationConfig(BaseModel):
    schema_version: str = SCHEDULER_SCHEMA_VERSION
    strict: bool = True
    require_resolved_config_hash_match: bool = True
    position_tolerance_m: float = 1.0e-5
    angle_tolerance_rad: float = 1.0e-7
    velocity_tolerance: float = 1.0e-6
    replay_file: str | None = None
```

`WorldSnapshot`：

```python
class WorldSnapshot(BaseModel):
    schema_version: str = SCHEDULER_SCHEMA_VERSION
    snapshot_id: str
    episode_id: str
    frame_index: int
    time_s: float
    decision_time_bucket: int
    crane_states: tuple[CraneState, ...]
    crane_configs: tuple[CraneConfig, ...]
    weather_state: WeatherState
    visibility_context: WeatherVisibilityContext
    tasks: tuple[Task, ...] = Field(default_factory=tuple)
    task_queues: tuple[TaskQueue, ...] = Field(default_factory=tuple)
    task_contexts: dict[str, TaskObservationContext | IdleObservationContext] = Field(default_factory=dict)
    current_commands: dict[str, ExecutedCommand] = Field(default_factory=dict)
    current_control_targets: dict[str, ControlTarget] = Field(default_factory=dict)
    recent_decisions: dict[str, list[dict]] = Field(default_factory=dict)
    recent_events: dict[str, list[dict]] = Field(default_factory=dict)
```

schema 约束：

- `snapshot_id` 稳定、可追踪，建议 `SNAP_{episode_id}_{frame_index:06d}`。
- `decision_time_bucket = round(time_s / llm_decision_interval_s)` 或等价整数桶，具体算法由 Task 02/04 固化。
- `crane_states.crane_id` 唯一。
- `crane_configs.crane_id` 唯一，且覆盖所有 `crane_states`。
- `current_commands` key 与 `ExecutedCommand.crane_id` 一致。
- `current_control_targets` key 与 `ControlTarget.crane_id` 一致。
- `WorldSnapshot` 不包含 offline label、future min distance、LLM raw response、LLM reason 或 provider secret。

命令存储状态：

```python
class StoredCommand(BaseModel):
    schema_version: str = SCHEDULER_SCHEMA_VERSION
    crane_id: str
    command: ExecutedCommand
    applied_at_s: float
    expires_at_s: float
    source: Literal["decision", "replay", "expired_neutral_stop", "llm_timeout_neutral_stop", "startup_neutral_stop"]

class CommandStoreSnapshot(BaseModel):
    schema_version: str = SCHEDULER_SCHEMA_VERSION
    time_s: float
    commands: dict[str, StoredCommand]
```

结果对象：

```python
class TerminalStatusCandidate(BaseModel):
    schema_version: str = SCHEDULER_SCHEMA_VERSION
    status: EpisodeStatus
    source_module: str
    reason: str
    time_s: float
    frame_index: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)

class FrameStepResult(BaseModel):
    schema_version: str = SCHEDULER_SCHEMA_VERSION
    frame_index: int
    time_s: float
    status: EpisodeStatus
    snapshot_id: str | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)

class EpisodeResult(BaseModel):
    schema_version: str = SCHEDULER_SCHEMA_VERSION
    episode_id: str
    status: EpisodeStatus
    final_time_s: float
    final_frame_index: int
    reason: str | None = None
    terminal_candidate: TerminalStatusCandidate | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
```

错误：

```python
class SchedulerError(RuntimeError):
    error_code: str
    episode_status: EpisodeStatus
    source_module: str
    details: dict[str, Any]
```

最低错误码：

```text
SCH_E_INVALID_CONFIG -> startup_error
SCH_E_INVALID_SNAPSHOT -> failed_invalid_state
SCH_E_COMMAND_STORE -> failed_invalid_state
SCH_E_FRAME_LOOP -> failed_invalid_state
SCH_E_REPLAY_MISMATCH -> failed_replay_mismatch
SCH_E_STOPPED_BY_USER -> stopped_by_user
```

## 前置依赖

- `RuntimeMode`、`LLMSchedulingMode`、`StrEnum`。
- `SimConfig`、`ResolvedConfig`。
- `CraneConfig`、`CraneState`。
- `Task`、`TaskQueue`。
- `WeatherState`、`WeatherVisibilityContext`。
- `ExecutedCommand`、`ControlTarget`。
- F 的 `TaskObservationContext` / `IdleObservationContext`，或在实现阶段用 `Any` / protocol 解除循环导入。

## 验收标准（具体、可测试）

- `SchedulerConfig.from_config()` 能从 `ResolvedConfig`、dict 和已有 typed config 中提取 `dt_s`、`duration_s`、`controller_hz`、`llm_decision_interval_s`、`RuntimeMode`。
- `SchedulerConfig` 拒绝 `dt_s <= 0`、`duration_s <= 0`、`controller_hz <= 0`、`llm_decision_interval_s <= 0`。
- `EpisodeStatus` 至少覆盖 running、completed、timeout、failed_collision、failed_invalid_state、llm_failed、failed_replay_mismatch、failed_recovery_blocked、failed_recovery_timeout、stopped_by_user。
- `WorldSnapshot` 拒绝重复 crane state id、重复 crane config id、state/config 缺失。
- `WorldSnapshot` 拒绝 extra 字段。
- `WorldSnapshot` 拒绝 NaN/Inf 数值。
- `WorldSnapshot` 不接受 `offline_label`、`future_min_distance`、`llm_reason` 等额外字段。
- `StoredCommand.expires_at_s == command.time_s + command.command_duration_s` 或等价明确字段。
- `CommandStoreSnapshot.commands` key 与 stored command crane id 一致。
- `TerminalStatusCandidate` 可序列化为 JSON，用于 recorder/API。

## 测试要点（正常 + 边界 + 异常）

- 正常：用两台塔吊、两条命令、天气、任务队列构造完整 `WorldSnapshot`。
- 正常：从测试 fixture 的 resolved config dict 构造 `SchedulerConfig`。
- 边界：空 tasks、空 recent_events、无 current commands 时 snapshot 仍合法。
- 边界：`min_duration_s=0`、`completion_cooldown_s=0` 合法。
- 异常：重复 `CraneState.crane_id`。
- 异常：`current_commands={"C2": command_for_C1}`。
- 异常：`dt_s=0`、`llm_decision_interval_s=-1`。
- 防泄漏：向 `WorldSnapshot` 注入 `offline_risk_label`、`future_min_distance_m`、`raw_llm_response` 应因 `extra="forbid"` 失败。
