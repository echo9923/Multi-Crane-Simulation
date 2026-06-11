# Task 02：Mechanical Safety Layer

## 任务目标

实现始终生效的基础机械安全层，把单台塔吊的 `ParsedCommand` 限制在机械速度、加速度、行程、高度、载重、力矩、deadman 和 emergency stop 合同内，产出 `MechanicalLimitResult` 和初步 `ExecutedCommand`。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/sim/safety.py`。
- 实现单塔 `ParsedCommand -> ExecutedCommand` 的机械安全检查。
- 根据 `CraneModelSpec.slew_speed_max_rad_s` 和 `slew_acc_max_rad_s2` 限制回转动作。
- 根据 `CraneConfig.trolley_r_min_m/trolley_r_max_m` 和 `CraneModelSpec.trolley_speed_max_m_s` 限制小车动作。
- 根据 `CraneConfig.hook_h_min_world_m/hook_h_max_world_m`、`CraneModelSpec.cable_length_min_m/cable_length_max_m` 和 `hoist_speed_max_m_s` 限制起升动作。
- 使用 `CraneModelSpec.capacity_at_radius_t()`、`is_load_allowed()` 和 `moment_at_radius_t_m()` 检查载重曲线与力矩。
- `deadman_pressed=False` 时所有运动轴置 neutral/0，保留 horn 与 task_action 的合同处理。
- `emergency_stop=True` 时所有运动轴置 neutral/0，并记录 emergency stop。
- 记录 `moment_limit`、`overload_prevented`、`trolley_limit`、`hoist_limit`、`slew_limit`、`deadman_released`、`emergency_stop` 等事件。

不做：

- 不计算多塔风险。
- 不执行 S0/S1/S2/S3 风险干预。
- 不判定禁区。
- 不判定碰撞。
- 不把命令转成连续 `ControlTarget`。
- 不推进物理状态。
- 不判定 attach/release 业务合法性。

## 接口与数据结构（签名级别）

```python
GEAR_TO_SPEED_SCALE: dict[int, float] = {
    0: 0.0,
    1: 0.2,
    2: 0.4,
    3: 0.6,
    4: 0.8,
    5: 1.0,
}

def apply_mechanical_safety(
    *,
    command: ParsedCommand,
    state: CraneState,
    config: CraneConfig,
    dt_s: float,
) -> tuple[ExecutedCommand, MechanicalLimitResult]:
    ...

def estimate_axis_velocity(
    *,
    axis: Literal["slew", "trolley", "hoist"],
    direction: str,
    gear: int,
    config: CraneConfig,
) -> float:
    ...

def command_would_exceed_trolley_limits(
    *,
    state: CraneState,
    config: CraneConfig,
    direction: Literal["in", "out", "neutral"],
    gear: int,
    dt_s: float,
) -> bool:
    ...

def command_would_exceed_hoist_limits(
    *,
    state: CraneState,
    config: CraneConfig,
    direction: Literal["up", "down", "neutral"],
    gear: int,
    dt_s: float,
) -> bool:
    ...

def command_would_exceed_load_or_moment(
    *,
    state: CraneState,
    config: CraneConfig,
    proposed_trolley_r_m: float,
) -> bool:
    ...
```

回转限速 MVP 可以只基于当前 `theta_dot_rad_s` 与目标方向/档位判断是否超过 `slew_speed_max_rad_s`；角加速度限制需要使用当前 `theta_dot_rad_s`、目标速度和 `dt_s`，不允许瞬间跳到超过 `slew_acc_max_rad_s2 * dt_s` 的速度意图。

## 前置依赖

- Task 01 的 `ExecutedCommand`、`MechanicalLimitResult` 和事件 schema。
- 模块 G 的 `ParsedCommand`。
- 模块 B 的 `CraneConfig` 和 `CraneModelSpec`。
- 模块 C 的 `CraneState`。

## 验收标准（具体、可测试）

- 机械安全层在 S0/S1/S2/S3 下都被调用，且行为一致。
- 合法命令在未触发限制时 `modified=False`，executed 手柄与 raw 手柄一致。
- `deadman_pressed=False` 时 slew/trolley/hoist 全部 neutral/0，并记录 `deadman_released`。
- `emergency_stop=True` 时 slew/trolley/hoist 全部 neutral/0，并记录 `emergency_stop`。
- 小车已经在 `trolley_r_max_m` 附近且继续 out 会越界时，trolley 轴被 clamp 到 neutral/0。
- 小车已经在 `trolley_r_min_m` 附近且继续 in 会越界时，trolley 轴被 clamp 到 neutral/0。
- 吊钩已经在 `hook_h_max_world_m` 附近且继续 up 会越界时，hoist 轴被 clamp 到 neutral/0。
- 吊钩已经在 `hook_h_min_world_m` 附近且继续 down 会越界时，hoist 轴被 clamp 到 neutral/0。
- 载重超过 `capacity_at_radius_t(proposed_radius)` 时，危险方向被阻止并记录 `overload_prevented`。
- `moment_at_radius_t_m(load_weight_t, proposed_radius)` 超过 `rated_moment_t_m` 时，危险方向被阻止并记录 `moment_limit`。
- 回转目标速度或加速度超过模型上限时，slew 轴被降档或 neutral，且记录 `slew_limit`。
- 机械限位导致的修改不记录 `intervention_applied`，只进入 mechanical events。

## 测试要点（正常 + 边界 + 异常）

- 正常：合法三轴命令不被修改；deadman pressed 且无超限时输出保持 raw。
- 边界：小车和吊钩正好位于 min/max；gear=0 和 gear=5；载重等于容量；力矩等于额定力矩。
- 异常：dt_s <= 0、command.crane_id 与 state/config 不一致、缺失模型能力字段时抛 `SAFETY_E_INVALID_STATE`。
- 合同：S0 模式下仍执行机械限位；被限位命令保留完整 `raw_command`。
