# Task 04：Stop And Safety Modes

## 任务目标

实现模块 I 的停止与安全模式：neutral stop、命令到期 neutral stop、deadman 安全停止、emergency stop 紧急制动和 hold position。

## 范围

做：

- 定义控制模式选择 helper：`resolve_controller_mode(...)`。
- 对 gear 0 或 direction neutral 的单轴命令产生该轴零期望速度，并继续使用 Task 03 的平滑过渡。
- 对整条 command 过期的情况产生三轴零期望速度，mode 为 `expired_neutral_stop`。
- 对 `deadman_pressed=False` 忽略所有手柄输入，三轴零期望速度，mode 为 `deadman_stop`。
- 对 `emergency_stop=True` 三轴零期望速度，mode 为 `emergency_stop`，`ControlTarget.emergency_stop=True`。
- 对 hold position 输入或等价内部模式三轴零期望速度，`ControlTarget.hold_position=True`。
- 在 `ControllerDiagnostic` 中记录 mode、command expired、deadman 和 emergency flags。

不做：

- 不新增 H 的安全审查逻辑。
- 不判断是否碰撞或是否进入禁区。
- 不在 `ControlTarget` 中写入安全原因文本；原因只进入 diagnostic。
- 不让 emergency stop 绕过数值校验或身份校验。

## 接口与数据结构

```python
ControllerMode = Literal[
    "normal",
    "neutral_stop",
    "expired_neutral_stop",
    "deadman_stop",
    "emergency_stop",
    "hold_position",
]

def is_command_expired(
    *,
    command: ExecutedCommand,
    now_s: float | None,
) -> bool:
    ...

def resolve_controller_mode(
    *,
    command: ExecutedCommand,
    now_s: float | None,
    hold_position: bool = False,
) -> ControllerMode:
    ...
```

模式优先级：

```text
emergency_stop
  > hold_position
  > deadman_stop
  > expired_neutral_stop
  > neutral_stop
  > normal
```

说明：

- `emergency_stop` 最高优先级，并设置 `ControlTarget.emergency_stop=True`。
- `hold_position` 是控制层内部或调度器明确要求的保持模式，设置 `ControlTarget.hold_position=True`。
- `deadman_stop` 不设置 `emergency_stop`，但三轴目标为零并平滑停止。
- `expired_neutral_stop` 要求 `now_s` 可用；若 `now_s is None`，不在 I 内判定过期，由 J 保证传入未过期命令或生成 neutral command。
- `neutral_stop` 表示三轴命令都是 neutral/gear 0；单轴 neutral 则只让该轴期望为零，不一定改变整条 command mode。

## 前置依赖

- Task 02 的档位映射 helper。
- Task 03 的平滑过渡 helper。
- `ExecutedCommand.time_s` 与 `command_duration_s`。

## 验收标准

- gear 0 或 direction neutral 的轴不会瞬间清零，而是按最大加速度逐步接近 0。
- `now_s > command.time_s + command.command_duration_s` 时 mode 为 `expired_neutral_stop`，三轴期望为 0。
- `now_s == command.time_s + command.command_duration_s` 建议仍视为有效；`>` 才过期，避免边界抖动。
- `deadman_pressed=False` 时忽略所有非零手柄输入，三轴平滑停止。
- `emergency_stop=True` 时忽略所有非零手柄输入，三轴按最大减速度停止，并设置 `ControlTarget.emergency_stop=True`。
- `hold_position=True` 时三轴目标为 0，并设置 `ControlTarget.hold_position=True`。
- 模式优先级确定且可测试：emergency 覆盖 hold、deadman 和 expiry。
- 所有停止模式仍遵守速度上限和加速度上限。

## 测试要点

- 正常：单轴 neutral，其他轴继续正常映射。
- 到期：命令时间 10.0、duration 1.0、now 11.01 进入 expired neutral stop。
- 边界：now 11.0 未过期；now `None` 不判定过期。
- deadman：给 gear 5 非零输入，但输出朝零接近。
- emergency：给 gear 5 非零输入，但输出 emergency flag 且朝零接近。
- 优先级：emergency + deadman + expired 同时出现时 mode 为 `emergency_stop`。
