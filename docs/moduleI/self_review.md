# Module I 阶段二自审

## 审查范围

本次自审覆盖以下阶段一产物：

- `docs/moduleI/README.md`
- `docs/moduleI/overview.md`
- `docs/moduleI/task01_controller_schema.md`
- `docs/moduleI/task02_gear_to_velocity.md`
- `docs/moduleI/task03_smooth_transition.md`
- `docs/moduleI/task04_stop_and_safety_modes.md`
- `docs/moduleI/task05_controller_orchestrator.md`
- `docs/moduleI/task06_tests_and_acceptance.md`

本阶段只产出文档，没有写实现代码、测试代码或运行时配置。

## 任务重叠检查

结论：任务之间有必要衔接，但职责边界清楚，没有重复实现同一能力。

- Task 01 只定义 schema、默认档位表、诊断和错误合同，不实现计算。
- Task 02 只做离散档位、方向和 `speed_scale` 到期望速度的映射。
- Task 03 只做速度限幅、加速度限制和平滑过渡。
- Task 04 只做停止和安全模式选择，以及将模式转换为零期望速度。
- Task 05 是唯一 orchestrator，把前置 helper 组装成 `ControlTarget` 和 `ControllerDiagnostic`。
- Task 06 只定义测试与验收，不新增生产接口。

## 任务遗漏检查

结论：`目标.md` 列出的 Module I 能力均已覆盖。

- `ControllerConfig`、`ControllerDiagnostic`、三轴档位表：Task 01。
- slew/trolley/hoist 档位到实际速度映射：Task 02。
- `ExecutedAxisCommand.speed_scale` 乘性缩放：Task 02。
- 当前速度到目标速度的加速度限制和平滑过渡：Task 03。
- 输出不超过机械最大速度：Task 03、Task 06。
- gear 0 或 neutral 平滑停止：Task 04、Task 06。
- `command_duration_s` 到期 neutral stop：Task 04、Task 06。
- `deadman_pressed=False` 安全停止：Task 04、Task 06。
- `emergency_stop=True` 紧急制动：Task 04、Task 06。
- `Controller.from_config()`、`compute_target()`、`compute_batch()`：Task 05。
- 每次 `compute_target` 产出诊断：Task 05、Task 06。
- 规则司机和 LLM 司机共用同一接口：Task 05、Task 06。
- H->I->C 链路 smoke test：Task 06。
- `ControlTarget` 不包含任务语义或 LLM reason：README、overview、Task 01、Task 06。
- 数值异常映射到 `failed_invalid_state`：overview、Task 01、Task 03、Task 05、Task 06。

## 依赖顺序检查

结论：依赖顺序合理且无环。

```text
Task 01 controller schema
  -> Task 02 gear to velocity
  -> Task 03 smooth transition
  -> Task 04 stop and safety modes
  -> Task 05 controller orchestrator
  -> Task 06 tests and acceptance
```

说明：

- Task 02 依赖 Task 01 的 `ControllerConfig` 和诊断对象。
- Task 03 依赖 Task 02 的 desired velocity，并补齐速度 clamp 与加速度限制。
- Task 04 依赖 Task 02/03，把停止和安全模式转换为零期望速度后继续复用平滑逻辑。
- Task 05 是模块出口，依赖前四个任务。
- Task 06 依赖所有前置任务，并补充跨模块验收。

## 验收标准可测性检查

结论：每个验收标准都可以通过 pytest、Pydantic schema 校验、静态扫描或 H->I->C smoke test 验证。

- schema 验收可通过 `model_validate()`、`model_dump(mode="json")`、extra 字段和 NaN/Inf fixtures 验证。
- 档位映射可通过三轴方向和 gear 参数化测试验证。
- `speed_scale` 可通过同一 gear 下不同 scale 的数值断言验证。
- 平滑过渡可通过固定当前速度、目标速度、加速度和 dt 的 deterministic fixtures 验证。
- command expiry 可通过 `command.time_s`、`command_duration_s` 和 `now_s` 边界测试验证。
- deadman/emergency/hold 可通过非零输入但零期望输出的 fixtures 验证。
- 机械速度和加速度上限可通过构造低上限 `CraneModelSpec` 验证。
- batch 对齐可通过打乱 commands/states/models 顺序验证。
- `ControlTarget` 信息纯度可通过字段集合断言和额外字段校验验证。
- H->I->C 链路可用 `apply_mechanical_safety()` fixture、`Controller.compute_target()` 和 `step_crane_state()` 完成 smoke test。

## 与阶段一背景一致性检查

结论：文档与 `目标.md` 和当前代码合同基本一致，并显式标注了当前 schema 的一个待实现缺口。

- I 只消费 H 的 `ExecutedCommand`，不重新做 H 的安全审查。
- I 输出的 `ControlTarget` 继续使用已有 `backend/app/schemas/control.py` 作为唯一事实源。
- I 的诊断对象新增在 control schema 中，但不污染 `ControlTarget`。
- I 不构造 observation，不调用 LLM，不推进 task，不冻结 snapshot，不写 recorder 文件。
- 三轴 gear table 使用总方案 I.2 的实际速度，不复用 H 的通用比例表。
- 当前 `CraneModelSpec` 已有 slew 加速度，但未看到 trolley/hoist 加速度字段；Task 03 已把补齐这两个字段列为实现前置工作，避免加速度验收无法落地。
- 当前 C 的 `step_crane_state()` 已对 slew 做加速度 approach，对 trolley/hoist 直接 clip 速度；I 文档仍要求 I 输出已经加速度限制后的三轴速度目标，符合“离散意图 -> 连续物理”边界。

## 调整记录

- 在建议拆分基础上保留 6 个任务，并补充 `README.md` 作为模块索引、`self_review.md` 作为阶段二闸口记录。
- 将 command expiry 的时间输入写成 `now_s` 可选参数，避免仅靠 `command, state, dt` 无法可靠判断命令是否到期。
- 将 emergency stop 设为最高优先级，并明确会设置 `ControlTarget.emergency_stop=True`。
- 将 hold position 列为控制模式，但限定为调度器或控制器内部明确输入，不从任务语义推导。
- 明确 `compute_batch()` 按 `crane_id` 对齐，输出顺序跟 commands 一致。
- 明确 Task 03 需要补齐 trolley/hoist 加速度字段，否则无法满足总方案“各轴最大加速度”验收。

## 阶段闸口

阶段一和阶段二已完成。根据 `目标.md` 的硬性要求，现在应停下等待确认；收到确认后再进入阶段三逐任务实现、测试和提交。
