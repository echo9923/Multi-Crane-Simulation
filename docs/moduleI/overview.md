# Module I Overview：低层控制器边界

## 职责

模块 I 是离散命令链路进入连续物理世界前的控制转换层。它消费模块 H 已审查过的 `ExecutedCommand`，读取当前 `CraneState` 和 `CraneModelSpec`，输出模块 C 可直接消费的 `ControlTarget`。

命令链路位置如下：

```text
RawLLMResponse -> ParsedCommand -> ExecutedCommand -> ControlTarget -> CraneState
```

模块 I 不判断司机意图是否安全，也不推进物理状态。它只回答一个问题：在当前控制周期内，每台塔吊三条轴应该朝什么连续速度目标平滑靠近。

## 档位到速度映射

模块 I 使用总方案 I.2 的轴独立实际速度档位表：

| gear | slew rad/s | trolley m/s | hoist m/s |
|---:|---:|---:|---:|
| 0 | 0.0 | 0.0 | 0.0 |
| 1 | 0.15 | 0.08 | 0.1 |
| 2 | 0.3 | 0.15 | 0.2 |
| 3 | 0.5 | 0.3 | 0.35 |
| 4 | 0.65 | 0.4 | 0.5 |
| 5 | 0.8 | 0.5 | 0.6 |

方向只决定符号：

- slew：`left` 为负，`right` 为正，`neutral` 为零。
- trolley：`in` 为负，`out` 为正，`neutral` 为零。
- hoist：`down` 为负，`up` 为正，`neutral` 为零。

`ExecutedAxisCommand.speed_scale` 在查表后做乘性缩放。例如 trolley gear 4、direction `out`、speed scale `0.5` 的 raw target 为 `+0.4 * 0.5 = +0.2 m/s`。

若轴的档位速度超过 `CraneModelSpec` 对应机械最大速度，则最终目标必须被机械最大速度限幅，并在 `ControllerDiagnostic` 中记录。

## 平滑过渡策略

模块 I 的输出不是简单的档位查表结果，而是当前控制周期允许达到的中间速度目标。

控制周期由 `controller_dt_s = 1 / controller_hz` 得到；调度器也可以显式传入等价的 `dt_s`。对每个轴：

```text
desired_velocity = direction_sign * gear_velocity_table[axis][gear] * speed_scale
desired_velocity = clamp(desired_velocity, -axis_speed_max, +axis_speed_max)
max_delta = axis_acc_max * controller_dt_s
target_velocity = approach(current_velocity, desired_velocity, max_delta)
```

其中 `current_velocity` 来自 `CraneState`：

- slew：`theta_dot_rad_s`
- trolley：`trolley_v_m_s`
- hoist：`hoist_v_m_s`

平滑过渡默认采用加速和减速对称的最大加速度限制。后续若需要非对称减速度，可在 `ControllerConfig` 中扩展，但本阶段不引入未被总方案要求的额外配置。

## 输入

单台塔吊最小输入：

```python
def compute_target(
    command: ExecutedCommand,
    state: CraneState,
    model: CraneModelSpec,
    *,
    dt_s: float | None = None,
    now_s: float | None = None,
) -> tuple[ControlTarget, ControllerDiagnostic]:
    ...
```

说明：

- `command` 提供三轴离散档位、方向、`speed_scale`、deadman、emergency stop 和 `command_duration_s`。
- `state` 提供当前三轴速度，作为平滑过渡起点。
- `model` 提供速度与加速度上限。
- `dt_s` 未传入时使用 `ControllerConfig.controller_dt_s`。
- `now_s` 用于判断 `command.time_s + command.command_duration_s` 是否已过期；若未传入，则由调度器保证传入的 command 尚未过期或通过后续 controller state 维护命令年龄。

batch 输入：

```python
def compute_batch(
    commands: Sequence[ExecutedCommand],
    states: Sequence[CraneState],
    models: Mapping[str, CraneModelSpec] | Sequence[CraneModelSpec],
    *,
    dt_s: float | None = None,
    now_s: float | None = None,
) -> tuple[list[ControlTarget], list[ControllerDiagnostic]]:
    ...
```

batch 接口按 `crane_id` 对齐，不依赖列表顺序。

## 输出

模块 I 输出 `ControlTarget`：

```text
schema_version
crane_id
target_slew_velocity_rad_s
target_trolley_velocity_m_s
target_hoist_velocity_m_s
emergency_stop
hold_position
source_command_id
```

同时输出 `ControllerDiagnostic`，用于模块 L 记录：

```text
schema_version
diagnostic_id
crane_id
source_command_id
mode
controller_dt_s
per-axis desired/current/target velocities
per-axis speed clamp and acceleration clamp flags
input flags: deadman, emergency_stop, command_expired
error metadata when applicable
```

`ControlTarget` 是纯数值目标，不包含任务状态、任务 ID、LLM reason、risk reason 或 prompt 文本。

## 对内依赖

- A：读取 `ResolvedConfig.sim.controller_hz` 和必要时的 `sim.dt`。
- B：读取 `CraneModelSpec` 的速度与加速度上限。
- C：读取 `CraneState` 当前速度；输出 `ControlTarget` 给 `step_crane_state()`。
- H：读取 `ExecutedCommand`，尊重 H 已经写入的 `speed_scale` 和 safety flags。
- J：由调度器按 `controller_hz` 调用 I，并提供当前时刻、命令集合与状态集合。
- L：消费并记录 `ControlTarget` 与 `ControllerDiagnostic`。

## 非目标

模块 I 不做以下事情：

- 不解析或审查 `ParsedCommand`。
- 不根据禁区、载重、风险或碰撞重新修改命令。
- 不区分规则司机和 LLM 司机，也不为它们维护两套控制逻辑。
- 不计算任务阶段，不处理 attach/release 业务合法性。
- 不更新 `CraneState`，不计算 hook 几何，不做积分。
- 不冻结 snapshot，不控制 episode 主循环。
- 不写任何导出文件。

## 失败边界

模块 I 对以下情况抛出控制器专属错误，默认由 J 映射为 `failed_invalid_state`：

- command、state、model 的 `crane_id` 不一致，或 batch 中 ID 缺失、重复。
- `dt_s` 或 `controller_hz` 非有限、非正。
- 当前速度、模型上限、档位速度或计算结果为 NaN/Inf。
- `CraneModelSpec` 缺少必要加速度字段。
- 未知轴、未知方向或不符合 schema 的 command 进入内部 helper。

## 权威来源

若本文档与根目录 `目标.md` 或总方案冲突，以总方案 `0.7.1`、`0.7.2`、`0.7.3`、`I.1`、`I.2`、`I.3` 以及本轮 `目标.md` 为准。
