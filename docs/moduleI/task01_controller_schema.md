# Task 01：Controller Schema

## 任务目标

定义模块 I 的控制器配置、诊断对象、错误对象和三轴独立档位表，作为后续控制计算和记录的合同基础。

## 范围

做：

- 修改 `backend/app/schemas/control.py`。
- 保留已有 `ControlTarget` 字段和 `extra="forbid"` 合同。
- 新增 `CONTROLLER_SCHEMA_VERSION = "1.0"`。
- 新增 `ControllerConfig`，包含 `controller_hz`、三轴 gear table、紧急制动倍率或等价策略开关。
- 新增 `AxisControlDiagnostic`，记录单轴速度映射、限幅和平滑信息。
- 新增 `ControllerDiagnostic`，记录一次 `compute_target` 的模式、输入 flags、三轴诊断和来源命令。
- 新增 `ControllerError` 或控制器错误常量，用于数值异常映射到 `failed_invalid_state`。
- 所有新增 schema 使用 `extra="forbid"`、`allow_inf_nan=False`。

不做：

- 不实现档位到速度的计算逻辑。
- 不实现 controller orchestrator。
- 不修改 `ExecutedCommand`、`CraneState` 或 `CraneModelSpec` 的字段。
- 不在 schema 中加入任务语义、LLM reason 或 prompt 内容。

## 接口与数据结构

```python
CONTROLLER_SCHEMA_VERSION = "1.0"

DEFAULT_SLEW_GEAR_SPEEDS_RAD_S = {
    0: 0.0,
    1: 0.15,
    2: 0.3,
    3: 0.5,
    4: 0.65,
    5: 0.8,
}

DEFAULT_TROLLEY_GEAR_SPEEDS_M_S = {
    0: 0.0,
    1: 0.08,
    2: 0.15,
    3: 0.3,
    4: 0.4,
    5: 0.5,
}

DEFAULT_HOIST_GEAR_SPEEDS_M_S = {
    0: 0.0,
    1: 0.1,
    2: 0.2,
    3: 0.35,
    4: 0.5,
    5: 0.6,
}

class ControllerConfig(ControlBaseModel):
    schema_version: str = CONTROLLER_SCHEMA_VERSION
    controller_hz: float
    slew_gear_speeds_rad_s: dict[int, float]
    trolley_gear_speeds_m_s: dict[int, float]
    hoist_gear_speeds_m_s: dict[int, float]
    emergency_deceleration_multiplier: float = 1.0

    @property
    def controller_dt_s(self) -> float:
        ...

class AxisControlDiagnostic(ControlBaseModel):
    axis: Literal["slew", "trolley", "hoist"]
    direction: str
    gear: int
    speed_scale: float
    current_velocity: float
    desired_velocity_before_speed_clamp: float
    desired_velocity_after_speed_clamp: float
    target_velocity: float
    speed_clamped: bool = False
    acceleration_limited: bool = False
    speed_clamp_delta: float = 0.0
    acceleration_delta: float = 0.0
    max_velocity_abs: float
    max_acceleration_abs: float

class ControllerDiagnostic(ControlBaseModel):
    schema_version: str = CONTROLLER_SCHEMA_VERSION
    diagnostic_id: str
    crane_id: str
    source_command_id: str | None
    mode: Literal[
        "normal",
        "neutral_stop",
        "expired_neutral_stop",
        "deadman_stop",
        "emergency_stop",
        "hold_position",
    ]
    controller_dt_s: float
    command_time_s: float | None = None
    now_s: float | None = None
    command_duration_s: float | None = None
    command_expired: bool = False
    deadman_pressed: bool | None = None
    emergency_stop_requested: bool = False
    axes: list[AxisControlDiagnostic]
```

建议错误：

```python
CTRL_E_INVALID_STATE = "CTRL_E_INVALID_STATE"
CTRL_E_IDENTITY_MISMATCH = "CTRL_E_IDENTITY_MISMATCH"
CTRL_E_NUMERIC = "CTRL_E_NUMERIC"

class ControllerStateError(ValueError):
    error_code: str
    category: Literal["episode_failed"] = "episode_failed"
    episode_status: Literal["failed_invalid_state"] = "failed_invalid_state"
    crane_id: str | None
    field_path: str | None
```

## 前置依赖

- 已有 `backend/app/schemas/control.py` 中的 `ControlTarget`。
- 已有 `backend/app/schemas/config.py` 中的 `SimConfig.controller_hz`。
- Pydantic v2 可用，当前 schema 已使用 `ConfigDict`。

## 验收标准

- `ControllerConfig()` 默认档位表与总方案 I.2 完全一致。
- `ControllerConfig.controller_dt_s == 1 / controller_hz`。
- `controller_hz <= 0`、NaN、Inf 会校验失败。
- gear table 必须包含且只包含 gear `0..5`。
- gear table 的速度必须非负且有限。
- gear 0 速度必须为 0。
- `ControllerDiagnostic.model_dump(mode="json")` 可序列化。
- `ControllerDiagnostic` 额外字段会失败。
- `ControllerDiagnostic` 或 `AxisControlDiagnostic` 中的 NaN/Inf 会失败。
- `ControlTarget` 没有新增任务语义或 LLM reason 字段。

## 测试要点

- 正常：默认 `ControllerConfig`、完整 `ControllerDiagnostic` 构造和 JSON dump。
- 边界：gear table 缺少 gear、包含 gear 6、gear 0 非零、最大档非单调但合法速度时是否允许。建议要求非递减，避免档位语义混乱。
- 异常：NaN `controller_hz`、Inf axis velocity、额外字段、非法 mode。
