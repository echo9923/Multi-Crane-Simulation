# Task 04：Command Parser

## 任务目标

实现 `RawLLMResponse -> ParsedCommand` 的解析与校验，把 provider 原始内容转为 schema 合法的司机意图，并在失败时产出可反馈给 retry prompt 的结构化 validation errors。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/sim/command_parser.py`。
- 解析 raw content 中的 JSON 对象。
- 使用 `ParsedCommand` Pydantic schema 校验字段、枚举、extra、数值范围和 NaN/Inf。
- 校验 `direction/gear` 一致性。
- 校验 `command_duration_s` 在 `LLMConfig.command_duration.min_s/max_s` 范围内。
- 从 `RawLLMResponse` 补齐 `response_id`、`observation_id`、`source_snapshot_id`、`operator_id`、`crane_id`、`time_s` 等元数据，避免信任模型输出这些权威字段。
- 把 JSON decode error、schema validation error 和业务 validator error 转为 `CommandValidationError[]`。

不做：

- 不调用 provider。
- 不实现 retry/fallback。
- 不修改模型输出中的 joystick 命令来“帮它过校验”。
- 不执行机械安全、力矩、禁区或风险判断。
- 不写日志。

## 接口与数据结构（签名级别）

```python
class CommandParseError(RuntimeError):
    errors: list[CommandValidationError]

def extract_json_object(content: str) -> dict[str, Any]:
    ...

def parse_raw_llm_response(
    raw_response: RawLLMResponse,
    *,
    command_duration_min_s: float,
    command_duration_max_s: float,
) -> ParsedCommand:
    ...

def validation_errors_from_exception(exc: Exception) -> list[CommandValidationError]:
    ...
```

解析策略：

- 首选 `json.loads(content)`，要求 content 是一个 JSON object。
- 可以容忍 provider 在 content 前后包裹少量空白。
- 不容忍 Markdown fenced code、自然语言解释或多个 JSON 对象；这些应触发 retry，让模型纠正为严格 JSON。
- 模型输出中的 `schema_version`、`command_id`、`response_id`、`observation_id` 等元数据不是必填输入；parser 根据 raw response 和当前 observation 生成权威值。

## 前置依赖

- Task 01 的 command schema。
- Task 03 的 `RawLLMResponse`。
- `LLMConfig.command_duration`。

## 验收标准（具体、可测试）

- 合法 raw JSON 能解析为 `ParsedCommand`。
- parser 生成稳定非空 `command_id`，并保留 raw `response_id`。
- parser 使用 raw response 的 observation/crane/operator/snapshot/time 元数据，不信任模型伪造的元数据。
- invalid JSON 生成 `CommandValidationError(error_code="LLM_E_002", retryable=True)`。
- extra 字段被拒绝并指出 field path。
- 中文枚举被拒绝并指出 field path。
- `direction/gear` 不一致被拒绝。
- `command_duration_s < min_s` 或 `> max_s` 被拒绝。
- `confidence` 越界被拒绝。
- `NaN/Inf` 被拒绝。
- parser 不调用 H/I/C/D 模块，不访问全局状态。

## 测试要点（正常 + 边界 + 异常）

- 正常：完整合法 JSON、前后空白、reason 为中文。
- 边界：duration 等于 min/max，confidence 等于 0/1，horn true，emergency_stop true。
- 异常：空字符串、Markdown 包裹、数组 JSON、多个对象、缺字段、extra 字段、非法枚举、中文枚举、档位越界、duration 越界、NaN/Inf。
- 防越权：静态 import 扫描确认 parser 不导入 `physics`、`task_state_machine`、`control`、`weather` 或 `layout` 运行时逻辑。
