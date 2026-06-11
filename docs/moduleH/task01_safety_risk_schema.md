# Task 01：Safety and Risk Schema

## 任务目标

定义模块 H 的 `ExecutedCommand`、`OnlineRisk`、风险对结果、机械限位结果、禁区结果、干预记录和碰撞事件 schema，作为 H/I/F/J/L/K 之间安全对象的唯一事实源。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/schemas/risk.py`。
- 在 `backend/app/schemas/command.py` 中补充 `ExecutedCommand` 及必要的 executed 子对象。
- 定义 `SAFETY_SCHEMA_VERSION = "1.0"` 和 `RISK_SCHEMA_VERSION = "1.0"`。
- 定义 `RiskLevel` 枚举或 Literal 值：`safe/low/medium/high/near_miss/collision`。
- 定义 `RiskObjectType`：`jib/jib_tip/hook/load/cable/unknown`。
- 定义 `RiskPairResult`，表示一帧内一对塔吊的在线风险结果。
- 定义 `OnlineRisk`，聚合每帧所有塔吊对风险，并提供可转为 F 的 `OnlineRiskHint` 的字段。
- 定义 `MechanicalLimitResult`，记录机械限位、力矩限制、deadman 和 emergency stop 对命令的修改。
- 定义 `ForbiddenZoneResult`，记录禁区策略结果。
- 定义 `InterventionRecord`，记录 S2/S3 风险干预。
- 定义 `CollisionEvent`，记录碰撞对象、塔吊对、时间、距离和 episode 终止原因。
- 定义 `SafetyPipelineResult`，作为 H 给 J/I/L 的聚合返回对象。
- 定义稳定错误码常量：`SAFETY_*`、`RISK_*`、`COLLISION_*`。
- 所有 H 新增 Pydantic schema 使用 `extra="forbid"`、`allow_inf_nan=False`。

不做：

- 不实现机械限位算法。
- 不实现风险距离计算。
- 不实现禁区几何判断。
- 不实现碰撞检测。
- 不写 recorder。
- 不构造 observation。

## 接口与数据结构（签名级别）

```python
SAFETY_SCHEMA_VERSION = "1.0"
RISK_SCHEMA_VERSION = "1.0"

RiskLevel = Literal["safe", "low", "medium", "high", "near_miss", "collision"]
RiskObjectType = Literal["jib", "jib_tip", "hook", "load", "cable", "unknown"]

class ExecutedAxisCommand(CommandBaseModel):
    direction: str
    gear: int = Field(ge=0, le=5)
    speed_scale: float = Field(default=1.0, ge=0, le=1)
    source: Literal["raw", "mechanical_limit", "forbidden_zone", "risk_intervention"]

class ExecutedCommand(CommandBaseModel):
    schema_version: str = SAFETY_SCHEMA_VERSION
    command_id: str
    raw_command_id: str
    observation_id: str
    source_snapshot_id: str
    operator_id: str
    crane_id: str
    time_s: float = Field(ge=0)
    raw_command: ParsedCommand
    left_joystick: ExecutedLeftJoystickCommand
    right_joystick: ExecutedRightJoystickCommand
    deadman_pressed: bool
    emergency_stop: bool
    horn: bool
    command_duration_s: float = Field(ge=0)
    task_action: Literal["none", "request_attach", "request_release"]
    modified: bool
    modification_reasons: list[str] = Field(default_factory=list)
    mechanical_limit: MechanicalLimitResult | None = None
    forbidden_zone: ForbiddenZoneResult | None = None
    interventions: list[InterventionRecord] = Field(default_factory=list)

class RiskPairResult(RiskBaseModel):
    schema_version: str = RISK_SCHEMA_VERSION
    pair_id: str
    crane_id_a: str
    crane_id_b: str
    time_s: float = Field(ge=0)
    d_min_online_m: float = Field(ge=0)
    d_hat_min_m: float = Field(ge=0)
    ttc_hat_s: float | None = Field(default=None, ge=0)
    d_safe_effective_m: float = Field(gt=0)
    base_threshold_m: float = Field(gt=0)
    wind_extra_m: float = Field(ge=0)
    risk_level: RiskLevel
    nearest_object_a: RiskObjectType
    nearest_object_b: RiskObjectType
    relative_motion: Literal["opening", "stable", "closing", "unknown"]
    used_future_truth: bool = False
    confidence: float = Field(ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)

class OnlineRisk(RiskBaseModel):
    schema_version: str = RISK_SCHEMA_VERSION
    risk_id: str
    source_snapshot_id: str
    time_s: float = Field(ge=0)
    pairs: list[RiskPairResult]
    global_risk_level: RiskLevel
    nearest_pair_id: str | None = None
    nearest_neighbor_by_crane: dict[str, str | None] = Field(default_factory=dict)
    hint_by_crane: dict[str, OnlineRiskHint] = Field(default_factory=dict)

class MechanicalLimitResult(SafetyBaseModel):
    schema_version: str = SAFETY_SCHEMA_VERSION
    crane_id: str
    modified: bool
    applied_limits: list[str] = Field(default_factory=list)
    blocked_axes: list[str] = Field(default_factory=list)
    clamped_axes: list[str] = Field(default_factory=list)
    events: list[SafetyEvent] = Field(default_factory=list)

class ForbiddenZoneResult(SafetyBaseModel):
    schema_version: str = SAFETY_SCHEMA_VERSION
    crane_id: str
    policy_mode: ForbiddenZonePolicyMode
    violation_detected: bool
    blocked: bool
    zone_ids: list[str] = Field(default_factory=list)
    events: list[SafetyEvent] = Field(default_factory=list)

class InterventionRecord(SafetyBaseModel):
    schema_version: str = SAFETY_SCHEMA_VERSION
    intervention_id: str
    crane_id: str
    safety_mode: SafetyMode
    risk_level: RiskLevel
    action: Literal["none", "ignored_risk_hint", "limit_speed_on_high_risk", "force_stop_on_high_risk"]
    modified: bool
    reason: str
    pair_ids: list[str] = Field(default_factory=list)

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
    executed_commands: list[ExecutedCommand]
    online_risk: OnlineRisk
    collision: CollisionEvent | None = None
    episode_status: Literal["running", "failed_collision", "failed_invalid_state"] = "running"
    events: list[SafetyEvent] = Field(default_factory=list)
```

实现阶段可以根据已有 `CommandBaseModel` 拆分 `ExecutedLeftJoystickCommand`、`ExecutedRightJoystickCommand`，但必须保持 raw command、executed command、risk、intervention 与 collision 的可序列化边界。

## 前置依赖

- `backend/app/schemas/command.py` 已有 `ParsedCommand` 及双手柄 schema。
- `backend/app/schemas/enums.py` 已有 `SafetyMode`、`RiskPromptMode`、`ForbiddenZonePolicyMode`。
- `backend/app/schemas/observation.py` 已有 `OnlineRiskHint`。
- `backend/app/schemas/crane.py` 已有 `CraneConfig` 和 `CraneModelSpec`。
- `backend/app/schemas/state.py` 已有 `CraneState`。

## 验收标准（具体、可测试）

- `ExecutedCommand.model_validate()` 接受包含完整 `raw_command` 的合法对象。
- `ExecutedCommand` 保存 `raw_command_id`，且 `raw_command.command_id` 可追溯。
- `ExecutedCommand.modified=False` 时 `modification_reasons` 为空。
- `ExecutedCommand.modified=True` 时至少有一个 `modification_reasons`。
- H 新增 schema 全部拒绝 extra 字段。
- H 新增 schema 所有 float 字段拒绝 NaN/Inf。
- `RiskPairResult.used_future_truth` 默认并保持为 `False`。
- `RiskPairResult.risk_level` 只接受 `safe/low/medium/high/near_miss/collision`。
- `RiskPairResult` 距离字段不可为负。
- `OnlineRisk.pairs` 支持每帧每对塔吊的结果导出。
- `CollisionEvent.episode_status` 固定为 `failed_collision`。
- 错误码常量命名稳定，可被测试按前缀扫描。

## 测试要点（正常 + 边界 + 异常）

- 正常：构造 `ParsedCommand`、`ExecutedCommand`、`OnlineRisk`、`RiskPairResult`、`InterventionRecord`、`CollisionEvent` 并 `model_dump(mode="json")`。
- 边界：`speed_scale=0`、`speed_scale=1`、`confidence=0`、`confidence=1`、`ttc_hat_s=None`、无风险 pair 的单塔场景。
- 异常：extra 字段、NaN/Inf、非法 risk level、负距离、`CollisionEvent` 非 `failed_collision`。
- 合同：从 `OnlineRisk.hint_by_crane` 中取出的对象可直接传给模块 F 的 `build_safety_hint()`。
