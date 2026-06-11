# Task 01：Observation Schema

## 任务目标

定义模块 F 的 `Observation` 及所有子对象 Pydantic schema，作为 G/L 消费 observation 的唯一事实源。

## 范围

做：

- 新增 `backend/app/schemas/observation.py`。
- 定义 `OBSERVATION_SCHEMA_VERSION = "1.0"`。
- 所有 schema 使用 `extra="forbid"`、`allow_inf_nan=False`。
- 定义 `Observation`、`SelfStateSummary`、`TaskObservationSummary`、`VisibleNeighbor`、`WeatherObservationSummary`、`SafetyHint`、`AvailableActions`、`MemorySummary`、`JoystickCommandSummary` 等对象。
- 定义 F 的窄输入合同 `OnlineRiskHint`，供 Task 05 消费。

不做：

- 不实现从状态构造 observation 的逻辑。
- 不实现 prompt 字符串。
- 不实现 recorder writer。

## 接口与数据结构

```python
OBSERVATION_SCHEMA_VERSION = "1.0"

class Observation(BaseModel):
    schema_version: str
    observation_id: str
    source_snapshot_id: str
    operator_id: str
    crane_id: str
    time_s: float
    operator_profile: OperatorProfile
    risk_prompt_mode: RiskPromptMode
    task: TaskObservationSummary
    self_state: SelfStateSummary
    visible_neighbors: list[VisibleNeighbor]
    weather: WeatherObservationSummary
    safety_hint: SafetyHint | None
    available_actions: AvailableActions
    memory: MemorySummary

class OnlineRiskHint(BaseModel):
    source: Literal["online_risk"]
    risk_level: Literal["low", "medium", "high", "critical"]
    nearest_neighbor: str | None
    nearest_object_type: str | None
    clearance_now_m: float | None
    estimated_clearance_next_5s_m: float | None
    relative_motion: Literal["opening", "stable", "closing", "unknown"]
    confidence: float
    suggestion: str | None
```

## 前置依赖

- `RiskPromptMode`、`OperatorProfile`、`VisibilityLevel` 已在 `schemas/enums.py` 中存在。
- D/E schema 已提供任务和天气读取侧对象。

## 验收标准

- `Observation.model_validate()` 接受符合 F.3 结构的最小 JSON。
- 额外字段会失败。
- NaN/Inf 数值会失败。
- `schema_version` 默认等于 `"1.0"`。
- `risk_prompt_mode=R0` 时允许 `safety_hint=None`。
- `risk_prompt_mode=R1` 时 schema 允许非空 `SafetyHint`，但 R0/R1 语义由 Task 05/06 builder 测试。
- schema 中不存在禁用字段名：`future_min_distance`、`offline_ttc`、`planned_start_s`。

## 测试要点

- 正常：构造完整 observation 并 `model_dump(mode="json")`。
- 边界：空 `visible_neighbors`、空 `recent_decisions`、idle task。
- 异常：额外字段、NaN、非法 risk confidence、非法 action gear。

