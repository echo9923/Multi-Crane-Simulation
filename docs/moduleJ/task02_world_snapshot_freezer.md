# Task 02：WorldSnapshot Freezer

## 任务目标

实现 `freeze_world_snapshot(...) -> WorldSnapshot`，从当前帧可变运行态深拷贝并冻结只读快照，确保同一 decision time 多塔 observation 基于同一 snapshot。

## 范围：做什么 / 不做什么

做：

- 在 `backend/app/sim/scheduler.py` 中实现 `freeze_world_snapshot()`。
- 从当前 `CraneState[]`、`CraneConfig[]`、`WeatherState`、`Task[]`、`TaskQueue[]`、task contexts、current commands、recent events/decisions 构造 `WorldSnapshot`。
- 生成稳定 `snapshot_id` 和 `decision_time_bucket`。
- 将 `WorldSnapshot` 转换为 F 可消费的 `ObservationWorldSnapshot`。
- 保证快照对象不可变或等价只读：构造后修改原始运行态不影响 snapshot。
- 校验 snapshot 不含未来标签和 LLM reason。

不做：

- 不构造 `Observation`。
- 不调用 LLM/rule driver。
- 不计算 online risk。
- 不推进任务状态机。
- 不写 recorder。
- 不改变原始 `CraneState`、`Task`、`TaskQueue` 或 command store。

## 接口与数据结构（签名级别）

```python
def freeze_world_snapshot(
    *,
    episode_id: str,
    frame_index: int,
    time_s: float,
    llm_decision_interval_s: float,
    crane_states: Sequence[CraneState],
    crane_configs: Sequence[CraneConfig],
    weather_state: WeatherState,
    visibility_context: WeatherVisibilityContext,
    tasks: Sequence[Task] = (),
    task_queues: Sequence[TaskQueue] = (),
    task_contexts: Mapping[str, TaskObservationContext | IdleObservationContext] | None = None,
    current_commands: Mapping[str, ExecutedCommand] | None = None,
    current_control_targets: Mapping[str, ControlTarget] | None = None,
    recent_decisions: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    recent_events: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> WorldSnapshot:
    ...

def to_observation_snapshot(snapshot: WorldSnapshot) -> ObservationWorldSnapshot:
    ...
```

`decision_time_bucket` 建议规则：

```text
bucket = round(time_s / llm_decision_interval_s)
```

实现时必须避免浮点边界导致同一 `time_s` 在不同平台得到不同 bucket。可选方案：

```text
bucket = int(round((time_s + 1e-9) / interval))
```

只要任务文档和测试固化一种 deterministic 规则即可。

`to_observation_snapshot()` 映射规则：

- 保留 `snapshot_id`、`time_s`、`decision_time_bucket`。
- 复制 `crane_states`、`crane_configs`、`weather_state`、`visibility_context`。
- 派生或透传 `neighbor_map`、`task_contexts`、`current_commands`、`recent_decisions`、`recent_events`。
- 若 F 当前 `ObservationWorldSnapshot.current_commands` 仍为 `dict[str, ControlTarget]`，则传入 `current_control_targets`，不要把 `ExecutedCommand` 塞给 F。

## 前置依赖

- Task 01 scheduler schema。
- F 的 `ObservationWorldSnapshot` 输入合同。
- E 的 `WeatherVisibilityContext`。
- D 的 task context builder 或 idle context builder。
- 当前 command store 和 controller target 状态。

## 验收标准（具体、可测试）

- `freeze_world_snapshot()` 返回 `WorldSnapshot`，且 `snapshot.time_s == input time_s`。
- 同一输入多次调用产生相同 `snapshot_id`、`decision_time_bucket` 和 JSON 内容。
- 修改输入 `crane_states[0].theta_rad` 后，已冻结 snapshot 中的对应值不变。
- 修改输入 `tasks[0].status` 后，已冻结 snapshot 中的对应值不变。
- `WorldSnapshot.crane_states`、`crane_configs` 的 id 唯一且互相覆盖。
- `current_commands` key 必须匹配 `ExecutedCommand.crane_id`。
- `to_observation_snapshot()` 生成的 F snapshot 与原 J snapshot 共用同一 `snapshot_id`。
- 批量 observation 读取 `to_observation_snapshot(snapshot)` 后，所有 `Observation.source_snapshot_id` 相同。
- snapshot 不包含 offline future label、LLM raw response 或 LLM reason。
- `time_s`、`llm_decision_interval_s` 非有限或非法时抛 `SchedulerError`，默认 episode status 为 `failed_invalid_state` 或 startup config error。

## 测试要点（正常 + 边界 + 异常）

- 正常：两塔 active task，冻结 snapshot 后构造两个 observation，断言同一 `source_snapshot_id`。
- 正常：idle 塔吊无 active task，task context 使用 `IdleObservationContext`。
- 边界：无 current command，snapshot 的 `current_commands` 为空但合法。
- 边界：recent events 为空，memory 仍可构造。
- 边界：`time_s=0`，bucket 为 0。
- 异常：`llm_decision_interval_s=0`。
- 异常：crane config 缺少某个 state 对应 id。
- 异常：recent_decisions 中包含 secret 或 future/offline forbidden key；实现可选择在 J 层扫描并拒绝，或依赖 F 的 safe summary 过滤，但本任务至少要有防泄漏测试。
