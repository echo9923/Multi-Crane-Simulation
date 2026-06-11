# Task 03：Task Context Builder

## 任务目标

消费模块 D 的 `TaskObservationContext` 或 `IdleObservationContext`，构造 observation 中的 `task` 段。

## 范围

做：

- 实现 `build_task_summary()`。
- 输出当前阶段、任务类型、优先级、deadline、deadline 状态、地面信号提示。
- 对 pickup/dropoff/current target 相对自身 hook 的方向、距离和高度差做摘要。
- idle 时不输出下一任务、队列长度或 planned start 信息。

不做：

- 不读取 `TaskQueue`。
- 不推进任务状态机。
- 不重新生成地面信号提示，只消费 D 提供的 `ground_signal_hint`。

## 接口与数据结构

```python
def build_task_summary(
    *,
    task_context: TaskObservationContext | IdleObservationContext,
    observer_state: CraneState,
    distance_precision_m: float,
) -> TaskObservationSummary:
    ...
```

## 前置依赖

- Task 01 schema。
- D 的 `TaskObservationContext`、`IdleObservationContext`。

## 验收标准

- active task 输出 `stage`、`type`、`priority`、`deadline_s`、`deadline_missed`、`overtime_s`、`signal_hint`。
- pickup/dropoff relative direction、distance、height delta 只基于当前 hook 与自己任务点。
- idle task 的 pickup/dropoff/current target 摘要为 `None`，不出现下一任务字段。
- 所有距离和高度差按 `distance_precision_m` 圆整。
- 不输出 `planned_start_s`。

## 测试要点

- 正常：move_to_pickup、move_to_dropoff、idle。
- 边界：deadline 为 `None`、pickup/dropoff 缺失、hook 正好在目标点。
- 异常：context crane_id 与 state crane_id 不一致。

