# Task 02：Gear To Velocity

## 任务目标

实现单轴和三轴的档位到期望速度映射：根据 `ExecutedAxisCommand.direction`、`gear`、`speed_scale` 和轴类型得到带符号的连续期望速度。

## 范围

做：

- 新增 `backend/app/sim/controller.py`。
- 定义轴名类型：`Literal["slew", "trolley", "hoist"]`。
- 实现方向到符号的映射。
- 实现单轴 helper：`map_axis_to_desired_velocity(...)`。
- 实现三轴 helper：`map_command_to_desired_velocities(...)`。
- 应用 `ExecutedAxisCommand.speed_scale` 乘性缩放。
- 使用 Task 01 的 `ControllerConfig` 档位表。
- 生成每轴映射阶段的 `AxisControlDiagnostic` 基础字段。

不做：

- 不做加速度限制。
- 不做 command expiry、deadman 或 emergency stop。
- 不做机械限位、禁区或风险干预。
- 不推进物理状态。
- 不调用模块 H 的 `estimate_axis_velocity()`，因为该函数使用通用比例档位，不符合 I.2。

## 接口与数据结构

```python
AxisName = Literal["slew", "trolley", "hoist"]

def direction_sign(axis: AxisName, direction: str) -> int:
    ...

def map_axis_to_desired_velocity(
    *,
    axis: AxisName,
    axis_command: ExecutedAxisCommand,
    controller_config: ControllerConfig,
) -> float:
    ...

def map_command_to_desired_velocities(
    *,
    command: ExecutedCommand,
    controller_config: ControllerConfig,
) -> dict[AxisName, float]:
    ...
```

方向符号：

| axis | negative | zero | positive |
|---|---|---|---|
| slew | `left` | `neutral` | `right` |
| trolley | `in` | `neutral` | `out` |
| hoist | `down` | `neutral` | `up` |

计算公式：

```text
if direction == "neutral" or gear == 0:
    desired_velocity = 0.0
else:
    desired_velocity = sign * gear_table[axis][gear] * speed_scale
```

## 前置依赖

- Task 01 已定义 `ControllerConfig` 和默认 gear table。
- 已有 `ExecutedCommand`、`ExecutedAxisCommand` schema 会保证 gear 在 `0..5`，`speed_scale` 在 `[0, 1]`。

## 验收标准

- slew gear `1..5` 映射到 `0.15/0.3/0.5/0.65/0.8 rad/s` 的带符号速度。
- trolley gear `1..5` 映射到 `0.08/0.15/0.3/0.4/0.5 m/s` 的带符号速度。
- hoist gear `1..5` 映射到 `0.1/0.2/0.35/0.5/0.6 m/s` 的带符号速度。
- direction `neutral` 或 gear `0` 产出 `0.0`。
- `speed_scale=0.5` 时速度绝对值减半。
- `speed_scale=0.0` 时非 neutral 命令也产出 `0.0`。
- 未知轴或未知方向抛出 `ControllerStateError`，默认 episode status 为 `failed_invalid_state`。
- helper 不区分规则司机和 LLM 司机，不读取 `operator_id` profile 或 LLM 字段。

## 测试要点

- 正常：三轴所有 gear 和正负方向参数化测试。
- 边界：gear 0、neutral、speed scale 0、speed scale 1。
- 异常：绕过 Pydantic 传入未知 direction 或未知 axis，确认错误码和 field path。
- 合同：静态扫描或断言不引用 `backend.app.sim.safety.GEAR_TO_SPEED_SCALE`。
