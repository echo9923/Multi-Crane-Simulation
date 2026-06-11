# 模块 I：低层控制器模块任务索引

## 模块目标

模块 I 负责把模块 H 产出的 `ExecutedCommand` 转换为模块 C 可消费的 `ControlTarget`。它是命令链路中“离散手柄意图 -> 连续物理速度目标”的最后一级转换。

模块 I 必须统一服务规则司机和 LLM 司机：无论上游命令来自规则、LLM 还是安全干预后的 fallback，只要已经成为 `ExecutedCommand`，都进入同一套控制器逻辑。

权威来源为项目根目录下的 `目标.md` 以及总方案 `0.7.1`、`0.7.2`、`0.7.3`、`I.1`、`I.2`、`I.3`。若本目录文档与权威来源冲突，以权威来源为准，并同步修订本目录文档。

## 模块边界

模块 I 的输入：

- `ExecutedCommand`
- `CraneState`
- `CraneModelSpec`
- `ResolvedConfig.sim.controller_hz`
- 调度器提供的当前控制时刻或命令年龄信息

模块 I 的输出：

- `ControlTarget`
- `ControllerDiagnostic`

模块 I 拥有并实现：

- `ControllerConfig`
- `ControllerDiagnostic`
- 三轴独立档位表
- 档位、方向、`speed_scale` 到目标速度的映射
- 当前速度到目标速度的加速度限制和平滑过渡
- neutral stop、command expiry、deadman、emergency stop、hold position 模式
- `Controller.compute_target(...)`
- `Controller.compute_batch(...)`

模块 I 不允许做的事情：

- 不构造 `Observation`。
- 不调用 LLM provider，不生成或解析 `RawLLMResponse`。
- 不做机械安全、禁区策略、风险干预或碰撞判断。
- 不推进任务状态机。
- 不积分物理运动方程，不更新 `CraneState`。
- 不冻结 `WorldSnapshot`。
- 不写 Parquet、JSONL、summary 或 manifest 文件。
- 不把 `task_id`、`task_stage`、LLM reason 或任务语义写入 `ControlTarget`。

## 任务顺序

| 顺序 | 文档 | 目标 |
|---|---|---|
| 1 | [task01_controller_schema](task01_controller_schema.md) | 定义 `ControllerConfig`、`ControllerDiagnostic`、控制错误和三轴档位表 |
| 2 | [task02_gear_to_velocity](task02_gear_to_velocity.md) | 实现档位、方向、`speed_scale` 到三轴目标速度的映射 |
| 3 | [task03_smooth_transition](task03_smooth_transition.md) | 实现速度限幅、加速度限制和平滑过渡 |
| 4 | [task04_stop_and_safety_modes](task04_stop_and_safety_modes.md) | 实现 neutral stop、命令到期、deadman、emergency stop 和 hold position |
| 5 | [task05_controller_orchestrator](task05_controller_orchestrator.md) | 组装完整控制器接口和 batch 计算 |
| 6 | [task06_tests_and_acceptance](task06_tests_and_acceptance.md) | 定义模块 I 的单元、合同、集成和验收测试清单 |

## 全局实现约束

- `ControlTarget` 是控制目标的唯一事实源，字段必须通过 `extra="forbid"` 校验。
- `ControlTarget` 不得包含任务语义、LLM reason 或调度器内部字段。
- 三轴速度档位使用总方案 I.2 的轴独立实际速度表，不复用模块 H 中的通用 `GEAR_TO_SPEED_SCALE`。
- `ExecutedAxisCommand.speed_scale` 作为乘性缩放应用在档位基础速度之后，范围 `[0, 1]`。
- 方向只决定速度符号；gear 和 speed scale 只决定速度绝对值。
- 输出速度绝对值不得超过 `CraneModelSpec` 中对应轴的最大速度。
- 每周期速度增量不得超过 `CraneModelSpec` 中对应轴的最大加速度乘以控制周期。
- `gear=0` 或 `direction=neutral` 表示该轴目标为零，但必须按减速度平滑回零。
- `command_duration_s` 到期且没有新命令时进入 neutral stop。
- `deadman_pressed=false` 时忽略全部手柄输入，所有轴安全停止。
- `emergency_stop=true` 时执行紧急制动，输出 `ControlTarget.emergency_stop=True` 并按最大减速度收敛到零。
- 每次 `compute_target` 调用都必须产出 `ControllerDiagnostic`。
- 数值异常、身份不匹配、非有限速度或非法控制周期必须映射到 `failed_invalid_state`。

## 最小交付结果

完成本模块后，后续模块应能：

1. 从 H 的 `ExecutedCommand` 获得同一控制周期的 `ControlTarget`。
2. 保证规则司机和 LLM 司机共享同一控制器入口。
3. 在 C 的 `step_crane_state()` 前完成档位映射、速度限幅和平滑过渡。
4. 在停止和安全模式下稳定输出可解释的控制目标和诊断。
5. 让 L 能记录 `ControlTarget` 和 `ControllerDiagnostic`，用于复现与分析。
