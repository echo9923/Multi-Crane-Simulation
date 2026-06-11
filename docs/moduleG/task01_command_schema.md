# Task 01：Command Schema

## 任务目标

定义模块 G 的 `RawLLMResponse`、`ParsedCommand`、双手柄子对象、validation error 和调用记录 schema，作为 G/H/L 消费 LLM 命令的唯一事实源。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/schemas/command.py`。
- 定义 `COMMAND_SCHEMA_VERSION = "1.0"`。
- 所有 Pydantic schema 使用 `extra="forbid"`、`allow_inf_nan=False`。
- 定义 `RawLLMResponse`、`ParsedCommand`、`AxisCommand`、`LeftJoystickCommand`、`RightJoystickCommand`、`CommandValidationError`、`TokenUsage`、`LLMMessage`、`LLMCallRecord`、`OperatorDecisionResult`。
- 对齐总方案 G.3 输出 JSON Schema。
- 固化 `neutral_stop` command 工厂函数，供 retry/fallback 使用。
- 暴露 `ParsedCommand.model_json_schema()` 作为 prompt builder 的 schema 来源。

不做：

- 不调用 LLM provider。
- 不解析原始字符串。
- 不实现 retry。
- 不实现安全审查或 joystick 到速度的转换。
- 不写日志文件。

## 接口与数据结构（签名级别）

```python
COMMAND_SCHEMA_VERSION = "1.0"

class AxisCommand(CommandBaseModel):
    direction: Literal["left", "neutral", "right", "in", "out", "up", "down"]
    gear: int = Field(ge=0, le=5)

class LeftJoystickCommand(CommandBaseModel):
    slew: AxisCommand
    trolley: AxisCommand

class RightJoystickCommand(CommandBaseModel):
    hoist: AxisCommand

class RawLLMResponse(CommandBaseModel):
    schema_version: str = COMMAND_SCHEMA_VERSION
    response_id: str
    provider: LLMProviderName
    model: str
    observation_id: str
    source_snapshot_id: str
    operator_id: str
    crane_id: str
    time_s: float
    content: str
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float | None = None
    token_usage: TokenUsage | None = None

class ParsedCommand(CommandBaseModel):
    schema_version: str = COMMAND_SCHEMA_VERSION
    command_id: str
    response_id: str | None = None
    observation_id: str
    source_snapshot_id: str
    operator_id: str
    crane_id: str
    time_s: float
    left_joystick: LeftJoystickCommand
    right_joystick: RightJoystickCommand
    deadman_pressed: bool
    emergency_stop: bool
    horn: bool
    command_duration_s: float
    task_action: Literal["none", "request_attach", "request_release"]
    attention_target: str
    confidence: float = Field(ge=0, le=1)
    reason: str
    fallback_reason: str | None = None

class CommandValidationError(CommandBaseModel):
    schema_version: str = COMMAND_SCHEMA_VERSION
    error_code: str
    message: str
    field_path: str | None = None
    raw_fragment: str | None = None
    retryable: bool = True

class LLMCallRecord(CommandBaseModel):
    schema_version: str = COMMAND_SCHEMA_VERSION
    call_id: str
    observation: Observation
    messages: list[LLMMessage]
    raw_response: RawLLMResponse | None
    parsed_command: ParsedCommand | None
    validation_errors: list[CommandValidationError]
    provider: LLMProviderName
    model: str
    latency_ms: float | None
    token_usage: TokenUsage | None
    attempt_index: int
```

约束：

- `AxisCommand` 可以拆成 `SlewAxisCommand`、`TrolleyAxisCommand`、`HoistAxisCommand`，以便在类型层面限制各轴 direction；若保留一个类，则必须用 validator 按父字段校验。
- `direction="neutral"` 时 `gear == 0`。
- `gear == 0` 时 `direction == "neutral"`。
- `command_duration_s` 使用 `LLMConfig.command_duration.min_s/max_s` 做运行时校验；schema 默认测试使用 `[0.5, 3.0]`。
- `RawLLMResponse.raw_payload` 可保存 provider 原始 JSON，但不得包含完整 API key、authorization header 或 secret。

## 前置依赖

- `backend/app/schemas/enums.py` 已有 `LLMProviderName`、`OperatorProfile`、`LLMFallbackPolicy`、`StructuredOutputMode`、`LLMHistoryMode`。
- `backend/app/schemas/observation.py` 已有 `Observation`。
- `backend/app/schemas/task.py` 已有 `TaskActionSignal` 读取侧合同。

## 验收标准（具体、可测试）

- `ParsedCommand.model_validate()` 接受符合 G.3 的最小 JSON。
- 所有 command 子 schema 拒绝 extra 字段。
- 所有 float 字段拒绝 NaN/Inf。
- `confidence < 0` 或 `confidence > 1` 会失败。
- `gear < 0` 或 `gear > 5` 会失败。
- `direction=neutral, gear>0` 会失败。
- `direction!=neutral, gear=0` 会失败。
- slew/trolley/hoist 的 direction 枚举不可串用，例如 slew 不接受 `up`，hoist 不接受 `left`。
- `task_action` 只接受 `none/request_attach/request_release`，拒绝中文枚举。
- `model_json_schema()` 中没有 forbidden persisted secret 字段。
- `neutral_stop` 工厂函数输出 schema 合法的 `ParsedCommand`，且所有运动轴为 neutral/0。

## 测试要点（正常 + 边界 + 异常）

- 正常：构造完整 `ParsedCommand`、`RawLLMResponse`、`LLMCallRecord` 并 `model_dump(mode="json")`。
- 边界：`command_duration_s=0.5`、`command_duration_s=3.0`、`confidence=0`、`confidence=1`。
- 异常：extra 字段、NaN/Inf、非法枚举、档位范围越界、direction/gear 不一致、中文枚举。
- 防泄漏：`RawLLMResponse.raw_payload` 和 `LLMCallRecord` 不允许出现 `api_key`、`authorization`、`token`、`secret` 等字段名。
