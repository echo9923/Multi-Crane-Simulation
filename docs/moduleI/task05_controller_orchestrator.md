# Task 05：Controller Orchestrator

## 任务目标

组装完整模块 I 控制器，对外提供单台和批量计算接口，统一输出 `ControlTarget` 和 `ControllerDiagnostic`。

## 范围

做：

- 在 `backend/app/sim/controller.py` 中定义 `Controller`。
- 实现 `Controller.from_config(config)`，从 `ResolvedConfig` 或包含 `sim.controller_hz` 的对象创建 `ControllerConfig`。
- 实现 `compute_target(...)` 单台控制计算。
- 实现 `compute_batch(...)` 多台控制计算。
- 按 `crane_id` 校验 command、state、model 身份一致。
- 将 Task 02、03、04 的 helper 串起来：
  - resolve mode
  - map command to desired velocities
  - apply stop/safety desired override
  - smooth transition
  - build `ControlTarget`
  - build `ControllerDiagnostic`
- `ControlTarget.source_command_id` 写入 `ExecutedCommand.command_id`。
- 规则司机和 LLM 司机使用同一接口，不读取 profile 分支。

不做：

- 不实现调度器主循环。
- 不写文件。
- 不修改 C 的 `step_crane_state()`，除非为了对接新增加速度字段必须调整测试 fixture。
- 不在控制器中重新跑 H 的安全 pipeline。

## 接口与数据结构

```python
class Controller:
    def __init__(self, config: ControllerConfig) -> None:
        ...

    @classmethod
    def from_config(cls, config: object) -> "Controller":
        ...

    def compute_target(
        self,
        *,
        command: ExecutedCommand,
        state: CraneState,
        model: CraneModelSpec,
        dt_s: float | None = None,
        now_s: float | None = None,
        hold_position: bool = False,
    ) -> tuple[ControlTarget, ControllerDiagnostic]:
        ...

    def compute_batch(
        self,
        *,
        commands: Sequence[ExecutedCommand],
        states: Sequence[CraneState],
        models: Mapping[str, CraneModelSpec] | Sequence[CraneModelSpec],
        dt_s: float | None = None,
        now_s: float | None = None,
    ) -> tuple[list[ControlTarget], list[ControllerDiagnostic]]:
        ...
```

`from_config()` 支持以下输入形状：

```text
ResolvedConfig with .sim.controller_hz
ExperimentConfig or equivalent object with .sim.controller_hz
dict with {"sim": {"controller_hz": ...}}
ControllerConfig
```

`compute_batch()` 规则：

- commands、states、models 均按 `crane_id` 对齐。
- 输出 `ControlTarget` 顺序跟输入 `commands` 顺序一致。
- 缺少 state 或 model 抛出 `ControllerStateError`。
- 重复 `crane_id` 抛出 `ControllerStateError`。

## 前置依赖

- Task 01 schema。
- Task 02 gear mapping。
- Task 03 smooth transition。
- Task 04 stop and safety modes。

## 验收标准

- 单台正常命令输出 `ControlTarget`，三轴速度符合档位映射和平滑过渡。
- `ControlTarget.source_command_id == ExecutedCommand.command_id`。
- `ControlTarget.crane_id == command.crane_id == state.crane_id`。
- emergency stop 输出 `ControlTarget.emergency_stop=True`。
- hold position 输出 `ControlTarget.hold_position=True`。
- 每次 `compute_target` 都返回且只返回一个 `ControllerDiagnostic`。
- `compute_batch` 支持多塔，输出顺序稳定，且不依赖 states/models 输入顺序。
- command/state/model 身份不一致、缺失或重复时抛出 `ControllerStateError`。
- 控制器不读取 `raw_command.reason`，不根据 `operator_id` 或 profile 分叉。

## 测试要点

- 正常：gear 3 right/out/up 从静止开始产生三轴目标。
- 平滑：当前速度不为零时按 `acc * dt` approach。
- 安全：deadman、emergency、expired 三种模式通过 orchestrator 输出正确 target 和 diagnostic。
- batch：两台塔吊命令顺序为 C2/C1，states 顺序为 C1/C2，输出仍为 C2/C1。
- 异常：command C1 + state C2；重复 states；缺少 model。
- 合同：rule driver fixture 和 LLM driver fixture 都构造为 `ExecutedCommand`，经过同一 `Controller.compute_target()`。
