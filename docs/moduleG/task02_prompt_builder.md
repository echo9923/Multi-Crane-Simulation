# Task 02：Prompt Builder

## 任务目标

构造模块 G 的 system prompt、profile prompt、user prompt 和 retry correction prompt，把 `Observation`、操作员性格、可用动作和输出 schema 组合成稳定的 provider messages。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/sim/prompt_builder.py`。
- 定义五种 `OperatorProfile` 的中文 profile prompt 初版。
- 定义五种 profile 的行为参数说明，用于 prompt 和后续决策节奏，不用于篡改输出。
- 构造 system prompt：司机身份、局部观测边界、双手柄限制、严格 JSON 输出、英文字段/枚举要求。
- 构造 user prompt：注入 `Observation.model_dump(mode="json")`、`available_actions`、`command_duration_s` 范围、输出 schema。
- 构造 retry correction prompt：注入上一轮具体 validation errors，让模型只修正 JSON。
- 输出 provider 通用 `list[LLMMessage]`。

不做：

- 不调用 provider。
- 不解析 raw response。
- 不根据 profile 后处理改写 joystick、gear 或 task_action。
- 不读取 `WorldSnapshot`、`CraneState`、完整任务队列或 offline label。
- 不把完整 API key、provider secret、resolved config 原文注入 prompt。

## 接口与数据结构（签名级别）

```python
PROFILE_PROMPTS: dict[OperatorProfile, str]
PROFILE_BEHAVIOR_PARAMS: dict[OperatorProfile, dict[str, float]]

def get_profile_prompt(profile: OperatorProfile) -> str:
    ...

def get_profile_behavior_params(profile: OperatorProfile) -> dict[str, float]:
    ...

def build_system_prompt(
    *,
    profile: OperatorProfile,
    profile_prompt: str,
    behavior_params: dict[str, float],
) -> str:
    ...

def build_user_prompt(
    observation: Observation,
    *,
    command_schema: dict,
    command_duration_min_s: float,
    command_duration_max_s: float,
    command_duration_default_s: float,
) -> str:
    ...

def build_retry_prompt(
    validation_errors: list[CommandValidationError],
) -> str:
    ...

def build_operator_messages(
    observation: Observation,
    *,
    command_schema: dict,
    command_duration_min_s: float,
    command_duration_max_s: float,
    command_duration_default_s: float,
    retry_errors: list[CommandValidationError] | None = None,
) -> list[LLMMessage]:
    ...
```

message 格式：

```python
class LLMMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str
```

## Prompt 语言与枚举策略

- 业务说明、任务语义、安全说明、司机性格说明使用中文。
- JSON 字段名和枚举值固定使用英文。
- 明确禁止 `左/右/上/下/请求挂载` 等中文枚举。
- `reason` 允许中文。
- prompt 必须明确只能输出 JSON 对象，不得输出 Markdown 或额外解释。
- prompt 必须明确只允许从 `observation.available_actions` 中选择动作。

## 前置依赖

- Task 01 的 `ParsedCommand` schema、`CommandValidationError`、`LLMMessage`。
- 模块 F 的 `Observation` schema。
- `LLMConfig.command_duration`。
- `OperatorProfile` 枚举。

## 验收标准（具体、可测试）

- 五种 profile 都能生成非空且互不相同的 prompt。
- system prompt 包含局部观测边界、双手柄限制、严格 JSON、英文字段/枚举要求。
- user prompt 包含完整 observation JSON，且该 JSON 可被 `json.loads()` 解析。
- user prompt 包含 `available_actions` 中的动作空间。
- user prompt 包含 `command_duration_s` 的 min/default/max。
- user prompt 包含或引用 `ParsedCommand.model_json_schema()` 生成的输出 schema。
- retry prompt 包含每个 validation error 的 field path 和 message。
- prompt 中不出现 forbidden observation 泄漏字段：`future_min_distance`、`offline_ttc`、`offline_label`、`planned_start_s`、`neighbor_task_id`。
- prompt 中不出现 secret 字段：`api_key`、`authorization`、`token`、`secret`。
- 构造 prompt 不会修改传入的 `Observation`。

## 测试要点（正常 + 边界 + 异常）

- 正常：normal/conservative/aggressive/novice/fatigued 各生成一组 messages。
- 边界：R0 observation 无 safety hint；R1 observation 有 safety hint；idle task；空 visible neighbors；空 memory。
- 异常：传入非法 profile 不应绕过枚举校验；retry errors 为空时不生成 retry correction message。
- 静态扫描：prompt 文本必须包含英文枚举值，且不包含中文枚举示例作为可输出值。
