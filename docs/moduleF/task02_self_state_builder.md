# Task 02：Self State Builder

## 任务目标

从 `CraneState` 和 `CraneConfig` 构造自身状态摘要，让 LLM 看到自己的当前可操作状态而不是完整物理对象。

## 范围

做：

- 在 `backend/app/sim/observation.py` 中实现 `build_self_state_summary()`。
- 摘要回转运动、小车半径、吊钩高度、载荷状态、当前命令。
- 数值按 `distance_precision_m` 圆整。
- 将速度映射为人类可读运动：`slow_left/right`、`hold`、`in/out`、`up/down`。

不做：

- 不计算下一步控制。
- 不修改 `CraneState`。
- 不推断任务路径。

## 接口与数据结构

```python
def build_self_state_summary(
    *,
    state: CraneState,
    crane_config: CraneConfig,
    current_command: ControlTarget | None,
    distance_precision_m: float,
) -> SelfStateSummary:
    ...
```

输出字段：

```text
slew_angle_deg
slew_motion
trolley_r_m
hook_h_m
load_attached
load_type
load_weight_t
current_command
```

## 前置依赖

- Task 01 schema。
- `CraneState`、`CraneConfig`、`ControlTarget`。

## 验收标准

- 能从有效 state/config 构造 `SelfStateSummary`。
- `trolley_r_m`、`hook_h_m` 按 precision 圆整。
- 无 current command 时输出 neutral/hold 命令摘要。
- 速度符号映射稳定：回转正向为 `slow_left`，负向为 `slow_right`，小车正向为 `out`，负向为 `in`，升降正向为 `up`，负向为 `down`。
- 不输出完整 `root_position`、`tip_position`、`hook_position`。

## 测试要点

- 正常：带载和空载各一例。
- 边界：速度为 0 或接近 0 时显示 hold/neutral。
- 异常：state/config crane_id 不一致时抛 `ObservationBuildError`。

