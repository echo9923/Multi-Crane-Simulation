# Task 06：Observation Assembly

## 任务目标

组装完整 `Observation`，为单塔和批量决策提供模块 F 的正式入口函数。

## 范围

做：

- 新增 `ObservationWorldSnapshot` 输入合同。
- 实现 `build_observation()` 和 `build_observations_for_snapshot()`。
- 聚合 self state、task、visible neighbors、weather、safety hint、available actions、memory、operator profile。
- 生成稳定 `observation_id`。
- 将 schema 构造错误包装为 `ObservationBuildError`。

不做：

- 不冻结 snapshot。
- 不调用 LLM。
- 不写 JSONL。
- 不决定哪些塔吊 due for decision。

## 接口与数据结构

```python
class ObservationWorldSnapshot(BaseModel):
    schema_version: str = "1.0"
    snapshot_id: str
    time_s: float
    decision_time_bucket: int
    crane_states: list[CraneState]
    crane_configs: list[CraneConfig]
    weather_state: WeatherState
    visibility_context: WeatherVisibilityContext
    neighbor_map: dict[str, list[str]]
    task_contexts: dict[str, TaskObservationContext | IdleObservationContext]
    current_commands: dict[str, ControlTarget] = {}
    recent_decisions: dict[str, list[dict]] = {}
    recent_events: dict[str, list[dict]] = {}

def build_observation(
    *,
    snapshot: ObservationWorldSnapshot,
    crane_id: str,
    risk_prompt_mode: RiskPromptMode,
    operator_profile: OperatorProfile,
    online_risk: OnlineRiskHint | None = None,
    operator_id: str | None = None,
) -> Observation:
    ...

def build_observations_for_snapshot(
    *,
    snapshot: ObservationWorldSnapshot,
    crane_ids: list[str],
    risk_prompt_mode: RiskPromptMode,
    operator_profiles: dict[str, OperatorProfile],
    online_risks: dict[str, OnlineRiskHint] | None = None,
    operator_ids: dict[str, str] | None = None,
) -> list[Observation]:
    ...
```

## 前置依赖

- Task 01-05。
- A/B/C/D/E 的现有 schema。

## 验收标准

- 单塔 observation 可从 snapshot 构造并通过 schema 校验。
- 批量 observation 对同一 decision time 使用同一个 `source_snapshot_id`。
- 缺少 crane state/config/task context 时抛 `ObservationBuildError`，错误对象默认状态为 `failed_invalid_state`。
- `available_actions` 固定包含左右回转、小车内外、升降、gear 0-5、deadman、emergency_stop、task_action。
- `memory` 只包含已发生 recent decisions/events 摘要。
- observation JSON 可重复构造：同一 snapshot、seed、bucket、输入配置下输出完全一致。

## 测试要点

- 正常：单塔 active task、批量两塔。
- 边界：idle task、无 online risk、无 current command、无 memory。
- 异常：缺状态、缺配置、重复 state id。
- 防泄漏：完整 observation 序列化不包含 forbidden keys。

