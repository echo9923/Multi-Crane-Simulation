# Task 06：Tests And Acceptance

## 任务目标

定义模块 I 的完整测试与验收清单，覆盖 schema、档位映射、平滑过渡、停止模式、控制器编排、H->I->C 集成和错误路径。

## 范围

做：

- 新增 `backend/app/tests/test_controller.py`，覆盖 Task 01-05 的单元测试。
- 新增 `backend/app/tests/test_moduleI_acceptance.py`，覆盖模块 I 验收和跨模块链路。
- 必要时更新相邻模块 fixture，使 `CraneModelSpec` 的三轴加速度字段完整。
- 增加静态合同检查，确认 `ControlTarget` 不包含任务语义或 LLM reason。

不做：

- 不测试真实 LLM provider。
- 不测试 Parquet/JSONL writer 的具体文件格式。
- 不替代模块 H 的机械安全、禁区、风险和碰撞单元测试。
- 不在 I 的测试中推进完整 J 主循环。

## 接口与数据结构

建议测试文件：

```text
backend/app/tests/test_controller.py
  test_controller_config_defaults_match_module_i_tables
  test_map_axis_to_desired_velocity_*
  test_speed_scale_multiplies_desired_velocity
  test_smooth_transition_limits_acceleration
  test_neutral_stop_smoothly_returns_to_zero
  test_deadman_released_ignores_handle_input
  test_emergency_stop_sets_control_target_flag
  test_compute_batch_aligns_by_crane_id
  test_invalid_numeric_inputs_raise_controller_state_error

backend/app/tests/test_moduleI_acceptance.py
  test_all_handle_commands_convert_to_control_target
  test_outputs_do_not_exceed_mechanical_speed_limits
  test_acceleration_limits_hold_for_all_axes
  test_command_duration_expiry_enters_neutral_stop
  test_rule_and_llm_commands_share_same_controller
  test_h_to_i_to_c_smoke_step
  test_control_target_contains_no_task_or_llm_semantics
```

Required commands:

```bash
pytest backend/app/tests/test_controller.py -v

pytest backend/app/tests/test_controller.py \
       backend/app/tests/test_moduleI_acceptance.py -v

pytest backend/app/tests/test_command_schema.py \
       backend/app/tests/test_safety_mechanical.py \
       backend/app/tests/test_crane_state.py \
       backend/app/tests/test_physics.py -v
```

If the repository uses different existing file names for module C tests, add the closest equivalent command and keep the command above documented for the target contract.

## 前置依赖

- Task 01-05 implemented.
- Existing fixtures can construct `CraneModelSpec`, `CraneConfig`, `CraneState`, `ParsedCommand`, and `ExecutedCommand`.
- Module C `step_crane_state()` accepts `ControlTarget`.
- Module H can produce or fixture `ExecutedCommand`.

## 验收标准

- 所有手柄指令可转换为 `ControlTarget`。
- 三轴 gear table 与总方案 I.2 一致。
- `speed_scale` 对速度做乘性缩放。
- 输出速度不超过 `CraneModelSpec` 机械最大速度。
- 加速度和减速度不超过 `CraneModelSpec` 机械最大加速度。
- 手柄回中按减速度平滑停止，不瞬间清零。
- `command_duration_s` 到期后若无新命令自动进入 neutral stop。
- `deadman_pressed=False` 时全部轴安全停止。
- `emergency_stop=True` 时全部轴紧急制动，并设置 `ControlTarget.emergency_stop=True`。
- 每次 `compute_target` 产出 `ControllerDiagnostic`。
- 规则司机和 LLM 司机共用同一个 `Controller` 接口。
- H->I->C smoke test 可以从 `ExecutedCommand` 生成 `ControlTarget`，再调用 `step_crane_state()` 得到下一帧 `CraneState`。
- `ControlTarget` schema 仍然 `extra="forbid"`，不包含 `task_id`、`task_stage`、`reason`、`llm_reason`。
- 数值异常映射到 `failed_invalid_state`。

## 测试要点

- 正常：
  - 三轴 gear 1-5 正负方向。
  - 多塔 batch 控制。
  - H `speed_scale` 干预后的速度缩放。
- 边界：
  - gear 0。
  - direction neutral。
  - `now_s == command.time_s + command.command_duration_s`。
  - 机械最大速度低于默认 gear table。
  - 当前速度正好距离目标 `acc * dt`。
- 异常：
  - NaN/Inf `dt_s`、当前速度、模型上限。
  - command/state/model ID 不一致。
  - batch 重复 ID 或缺失 ID。
  - 负加速度或缺失加速度字段。
- 集成：
  - `apply_mechanical_safety()` 输出的 `ExecutedCommand` 经 I 转换，再被 C 消费。
  - 快速档位切换：gear 5 right 到 gear 5 left，输出跨零但单周期 delta 有界。
  - 多塔并发：至少两台塔吊同时控制，batch 输出与单台逐个计算一致。
