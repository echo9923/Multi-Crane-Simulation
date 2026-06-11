# Module G Overview：LLM 操作员决策边界

## 职责

模块 G 把模块 F 构造的 `Observation` 转换成结构化高层操作命令。它模拟“塔吊司机在当前决策时刻推双手柄、按安全开关、请求挂载/卸载”的行为，但不直接改变仿真状态。

G 的最小链路是：

```text
Observation
  + operator profile prompt
  + LLM provider config
  + command JSON schema
  -> messages
  -> RawLLMResponse
  -> ParsedCommand
  -> LLMCallRecord
```

其中 `RawLLMResponse` 和 `ParsedCommand` 的 owner 都是模块 G。`RawLLMResponse` 用于审计、解析和日志；`ParsedCommand` 是通过 Pydantic/schema 校验后的司机意图，交给模块 H 做机械安全、风险评估和干预。G 不产出 `ExecutedCommand`、`ControlTarget` 或 `CraneState`。

## 输入

G 读取以下对象：

- `Observation`：来自模块 F，是 G 唯一可读取的运行时状态入口。
- `Observation.operator_profile`：决定注入哪一种 profile prompt 和行为参数说明。
- `LLMConfig`：来自模块 A 的 resolved 配置，包含 `provider`、`model`、`base_url`、`api_key` / `api_key_env`、`timeout_s`、`max_retries`、`max_consecutive_failures`、`structured_output`、`context.history_mode`、`scheduling`、`fallback_policy` 和 `command_duration`。
- `OperatorAssignmentConfig` 或 resolved operator 分配结果：用于多塔独立 operator session。
- `ProviderRuntimeSecret`：来自 `backend/app/core/secret_resolver.py`，只在真实 provider 运行时使用，不得落盘完整 key。
- 历史上下文摘要：只允许包含已经发生的 observation、commands、任务阶段变化、风险事件和失败事件。
- replay 输入：模块 G 本地 replay provider 可读取历史 `ParsedCommand` 记录，并按 `snapshot_id + crane_id` 匹配。

## 输出

G 输出以下对象，供 H/L/J 消费：

```text
RawLLMResponse
ParsedCommand
CommandValidationError[]
LLMCallRecord
OperatorDecisionResult
```

建议的运行接口：

```python
def build_operator_messages(
    observation: Observation,
    *,
    profile_prompt: str,
    command_schema: dict,
    retry_errors: list[CommandValidationError] | None = None,
) -> list[LLMMessage]:
    ...

def parse_command(raw_response: RawLLMResponse) -> ParsedCommand:
    ...

def decide_one(
    observation: Observation,
    *,
    provider: LLMProvider,
    config: LLMConfig,
    session: OperatorSession,
) -> OperatorDecisionResult:
    ...
```

`OperatorDecisionResult` 是 G 给调度器/记录器的包装结果，至少包含当前 observation、messages、raw response、parsed command、validation errors、latency、token usage、provider、model、失败状态和 fallback 信息。模块 L 后续只读该对象落盘到 `commands.jsonl` 或等价日志。

## 对内依赖

- A：读取 `LLMConfig`、`OperatorConfig`、`OperatorProfile`、provider 脱敏摘要和运行时密钥解析结果。
- F：读取 `Observation`。G 不构造 observation，也不从 `WorldSnapshot`、`CraneState` 或 `Task` 绕过 F 读取状态。
- J：由调度器决定哪些塔吊在某个 decision time 需要调用 G，并提供同一 frozen snapshot 生成的 observations。G 可维护每塔 session，但不冻结 snapshot。
- H：消费 `ParsedCommand`，产出 `ExecutedCommand`。G 不执行安全审查。
- L：消费 `RawLLMResponse`、`ParsedCommand`、`LLMCallRecord` 和 validation errors 落盘。G 只产出对象，不直接写 Parquet/JSONL。

## 拥有对象

模块 G 拥有并实现：

- `COMMAND_SCHEMA_VERSION`
- `RawLLMResponse`
- `ParsedCommand`
- `AxisCommand`
- `LeftJoystickCommand`
- `RightJoystickCommand`
- `CommandValidationError`
- `TokenUsage`
- `LLMMessage`
- `LLMCallRecord`
- `OperatorSession`
- `OperatorDecisionResult`
- prompt builder
- command parser
- provider 抽象和 deepseek / minimax / mock / replay provider
- retry 与 fallback 逻辑
- 多塔 operator session 管理

模块 G 只读取或接收接口，不拥有：

- `ResolvedConfig` / `LLMConfig` schema 定义，归模块 A。
- `Observation`，归模块 F。
- `WorldSnapshot` 与单帧调度生命周期，归模块 J。
- `ExecutedCommand`、`OnlineRisk`、安全干预事件，归模块 H。
- `ControlTarget`，归模块 I。
- `CraneState`、`Task.status`、`TaskQueue`，分别归模块 C/D。
- JSONL/Parquet 文件写入器，归模块 L。

## 非目标

模块 G 不做以下事情：

- 不构造 `Observation`。
- 不读取 `WorldSnapshot`、`CraneState`、完整 `Task` 队列、offline label 或邻塔未来目标。
- 不修改 `CraneState`、`Task.status`、`TaskQueue`、`ControlTarget`。
- 不把 joystick + gear 转换为连续速度。
- 不做机械安全限位、力矩校验、禁区策略、多塔风险评估或风险干预。
- 不把 `ParsedCommand` 转为 `ExecutedCommand`。
- 不推进 episode clock，也不决定 collision/timeout 等全局终止；只报告 `llm_failed` 候选状态给 J。
- 不写 `commands.jsonl`、`command_replay.jsonl`、Parquet、manifest 或 WebSocket payload。
- 不通过后处理篡改 LLM 命令来伪造操作员性格。性格差异必须通过 profile prompt、行为参数、历史摘要语气和决策节奏体现。

## 关键边界规则

- `RawLLMResponse` 和 `ParsedCommand` 的 Pydantic schema 是唯一事实源，所有字段必须 `extra="forbid"`，数值拒绝 NaN/Inf。
- JSON 字段名和枚举值固定使用英文；业务说明、任务说明、安全说明和性格说明使用中文；`reason` 允许中文。
- `left_joystick.slew.direction` 只能是 `left/neutral/right`。
- `left_joystick.trolley.direction` 只能是 `in/neutral/out`。
- `right_joystick.hoist.direction` 只能是 `up/neutral/down`。
- `gear` 范围为 `[0, 5]`；`direction=neutral` 时 `gear` 必须为 `0`，`gear=0` 时 `direction` 必须为 `neutral`。
- `command_duration_s` 默认约 1 秒，范围来自 `LLMConfig.command_duration`，MVP 为 `[0.5, 3.0]`。
- `task_action` 只能是 `none/request_attach/request_release`。
- invalid JSON、schema validation error、provider timeout/API error 先 retry；单次决策重试耗尽后产出 `neutral_stop`；连续失败次数达到 `max_consecutive_failures` 时报告 `llm_failed`。
- replay provider 不调用 LLM，不读取完整全局状态；只按 `source_snapshot_id + crane_id` 找到唯一历史 `ParsedCommand`。总方案 0.7.9 的 `ExecutedCommand` 严格复现属于 J/H/L 全链路 replay，本地 G replay 只服务 Module G 单元测试和命令解析复现。

## 失败边界

G 的失败分为三类：

| 失败 | 默认处理 | 输出 |
| --- | --- | --- |
| provider timeout/API error | 当前决策 retry，耗尽后 `neutral_stop` | `CommandValidationError` 或 runtime failure record，`LLMCallRecord` |
| invalid JSON/schema error | 把具体错误注入 retry prompt，耗尽后 `neutral_stop` | raw response、validation errors、fallback `ParsedCommand` |
| 连续失败超阈值 | 通知 J 将 episode 标记为 `llm_failed` | `OperatorDecisionResult.episode_failure_reason` |

`neutral_stop` 是普通安全停止：所有运动轴 `neutral`、`gear=0`、`deadman_pressed=true`、`emergency_stop=false`、`horn=false`、`task_action=none`，`reason` 说明 fallback 原因。它不是急停。

## 权威来源

若本文档与总方案冲突，以项目根目录 `群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.5.8`、`0.5.9`、`0.5.15`、`0.5.16`、`0.7.1`、`0.7.2`、`0.7.3`、`0.7.6`、`0.7.8`、`0.8.1`、`0.8.2`、`0.8.3`、`0.8.4` 和 `模块 G` 的合同为准，并同步修订本文档。
