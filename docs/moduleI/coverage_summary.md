# Module I 覆盖总结

## 已覆盖

- `ControllerConfig`、`AxisControlDiagnostic`、`ControllerDiagnostic` schema 合同。
- 总方案 I.2 三轴独立档位表。
- direction、gear、`speed_scale` 到期望速度的映射。
- 三轴速度上限和加速度上限。
- gear 0、neutral、命令过期、deadman、emergency stop、hold position 停止模式。
- `Controller.compute_target()` 单台控制接口。
- `Controller.compute_batch()` 多塔并发接口，按 `crane_id` 对齐且保持命令顺序。
- 规则司机和 LLM 司机共享同一 `ExecutedCommand -> ControlTarget` 控制路径。
- H->I->C smoke 链路：`ParsedCommand -> apply_mechanical_safety() -> ExecutedCommand -> Controller.compute_target() -> step_crane_state()`。
- 快速档位切换跨零时的单周期加速度限制。
- NaN/Inf 和身份不一致错误映射到 `failed_invalid_state`。
- `ControlTarget` 不包含任务语义或 LLM reason。

## 未覆盖或后续模块覆盖

- 完整 J 调度主循环未覆盖；当前只覆盖 I 的 batch 接口和 H->I->C smoke 链路。
- L 的真实落盘格式未覆盖；当前验证了 `ControllerDiagnostic.model_dump(mode="json")` 可序列化。
- 真实 provider 和 LLM prompt 不属于 Module I，未测试。

## 验证命令

当前仓库没有 `backend/app/tests/test_physics.py` 文件，物理测试已拆分在 `test_physics_step.py`、`test_physics_world.py`、`test_physics_errors.py` 等文件中。因此 Module I 回归使用现有物理测试文件执行。
