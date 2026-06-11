# Task 03：Smooth Transition

## 任务目标

实现从当前速度到期望速度的平滑过渡，保证控制器输出速度不超过机械最大速度，且单周期速度变化不超过机械最大加速度。

## 范围

做：

- 在 `backend/app/sim/controller.py` 中新增速度 clamp、approach 和三轴平滑 helper。
- 对三轴分别读取当前速度：
  - slew：`CraneState.theta_dot_rad_s`
  - trolley：`CraneState.trolley_v_m_s`
  - hoist：`CraneState.hoist_v_m_s`
- 对三轴分别读取最大速度：
  - slew：`CraneModelSpec.slew_speed_max_rad_s`
  - trolley：`CraneModelSpec.trolley_speed_max_m_s`
  - hoist：`CraneModelSpec.hoist_speed_max_m_s`
- 对三轴分别读取最大加速度：
  - slew：`CraneModelSpec.slew_acc_max_rad_s2`
  - trolley：使用新增或现有 `CraneModelSpec.trolley_acc_max_m_s2`
  - hoist：使用新增或现有 `CraneModelSpec.hoist_acc_max_m_s2`
- 若当前 schema 尚无 trolley/hoist 加速度字段，应在本任务先补 schema 和配置 resolver 合同，再实现 helper。
- 写入 `AxisControlDiagnostic.speed_clamped`、`acceleration_limited`、clamp delta 和 acceleration delta。

不做：

- 不处理 deadman、expiry 或 emergency stop 模式选择。
- 不更新 `CraneState` 位置。
- 不处理 trolley 半径或 hook 高度边界；这些仍由 H/C 负责。

## 接口与数据结构

```python
def clamp(value: float, low: float, high: float) -> float:
    ...

def approach(current: float, target: float, max_delta: float) -> float:
    ...

def smooth_axis_velocity(
    *,
    axis: AxisName,
    current_velocity: float,
    desired_velocity: float,
    model: CraneModelSpec,
    dt_s: float,
    emergency: bool = False,
    controller_config: ControllerConfig,
) -> tuple[float, AxisControlDiagnostic]:
    ...

def smooth_command_velocities(
    *,
    desired_velocities: dict[AxisName, float],
    state: CraneState,
    model: CraneModelSpec,
    dt_s: float,
    controller_config: ControllerConfig,
) -> tuple[dict[AxisName, float], list[AxisControlDiagnostic]]:
    ...
```

平滑规则：

```text
clamped_desired = clamp(desired, -max_speed, +max_speed)
max_delta = max_acceleration * dt_s
target = approach(current, clamped_desired, max_delta)
target = clamp(target, -max_speed, +max_speed)
```

`approach()` 语义：

```text
delta = target - current
if abs(delta) <= max_delta:
    return target
return current + sign(delta) * max_delta
```

## 前置依赖

- Task 01 的 `AxisControlDiagnostic`。
- Task 02 的 desired velocity helper。
- `CraneModelSpec` 必须提供三轴最大速度和三轴最大加速度。

## 验收标准

- 当期望速度小于机械最大速度且速度差小于 `acc * dt` 时，输出等于期望速度。
- 当速度差大于 `acc * dt` 时，输出只变化 `acc * dt`。
- 正向加速、负向加速、减速到零、跨零反向都满足同一限制。
- 输出速度绝对值永远不超过 `CraneModelSpec` 对应最大速度。
- 若档位表速度高于机械最大速度，先做速度 clamp，再做平滑过渡，并记录 `speed_clamped=True`。
- `dt_s <= 0`、NaN、Inf 抛出 `ControllerStateError`。
- 当前速度或模型上限为 NaN/Inf 抛出 `ControllerStateError`。
- 诊断能区分 speed clamp 和 acceleration limit。

## 测试要点

- 正常：从 0 加速到 gear 5；从 gear 5 减速到 neutral；从正速度切到负方向。
- 边界：desired 正好等于 max speed；delta 正好等于 `acc * dt`；dt 很小。
- 异常：非有限当前速度、非正 dt、负加速度上限。
- 机械限制：构造模型最大速度低于默认 gear 5 速度，确认输出被 clamp 且诊断记录 clamp delta。
