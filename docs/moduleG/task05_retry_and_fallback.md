# Task 05：Retry 与 Fallback

## 任务目标

实现模块 G 的单次决策 retry、validation error 反馈、provider error 重试、`neutral_stop` fallback 和连续失败计数，为调度器提供 `llm_failed` 终止信号。

## 范围：做什么 / 不做什么

做：

- 在 `backend/app/sim/command_parser.py` 或新增 `backend/app/sim/operator_decision.py` 中实现单塔决策流程。
- 对 invalid JSON/schema validation error，把具体 `CommandValidationError` 注入 retry prompt。
- 对 provider timeout/API error 按 `LLMConfig.max_retries` 重试。
- 重试耗尽后生成 fallback `neutral_stop` 的 `ParsedCommand`。
- 每次尝试生成一个 `LLMCallRecord`。
- 维护每个 operator session 的连续失败计数。
- 连续失败计数达到 `LLMConfig.max_consecutive_failures` 时在 `OperatorDecisionResult` 中标记 `episode_failure_reason="llm_failed"`。
- 成功解析合法命令后清零对应 operator 的连续失败计数。

不做：

- 不改变 `CraneState`。
- 不把 fallback 直接变成 `ExecutedCommand`。
- 不调用 H 安全层。
- 不决定 episode 是否立即终止；只把 `llm_failed` 信号交给 J。
- 不把 operator profile 用于改写 LLM 输出。

## 接口与数据结构（签名级别）

```python
class OperatorSession(BaseModel):
    schema_version: str = COMMAND_SCHEMA_VERSION
    operator_id: str
    crane_id: str
    profile: OperatorProfile
    consecutive_failures: int = 0
    decision_index: int = 0
    history: list[LLMMessage] = Field(default_factory=list)

def decide_with_retry(
    observation: Observation,
    *,
    provider: LLMProvider,
    config: LLMConfig,
    session: OperatorSession,
) -> OperatorDecisionResult:
    ...

def build_neutral_stop_command(
    observation: Observation,
    *,
    response_id: str | None,
    reason: str,
    command_duration_s: float,
) -> ParsedCommand:
    ...
```

retry 尝试次数定义：

```text
max_retries = 0  => 首次失败后不再 retry，直接 fallback
max_retries = N  => 最多 1 + N 次 provider generate/parse 尝试
```

fallback command：

```text
left_joystick.slew = neutral/0
left_joystick.trolley = neutral/0
right_joystick.hoist = neutral/0
deadman_pressed = true
emergency_stop = false
horn = false
task_action = none
attention_target = "fallback_neutral_stop"
confidence = 0.0
reason = "LLM output invalid/timeout; fallback to neutral_stop."
fallback_reason = concrete failure summary
```

## 前置依赖

- Task 01 command schema。
- Task 02 prompt builder。
- Task 03 provider 抽象。
- Task 04 parser。
- `LLMConfig.max_retries`、`LLMConfig.max_consecutive_failures`、`LLMConfig.fallback_policy`。

## 验收标准（具体、可测试）

- 首次合法输出不重试，返回合法 `ParsedCommand`，连续失败计数清零。
- invalid JSON 后会构造 retry prompt，prompt 包含具体 validation error。
- schema validation error 后会 retry。
- timeout/API error 后会 retry。
- `max_retries=0` 时首次失败直接 fallback。
- retry 成功时返回成功命令，并记录之前失败尝试的 validation errors/call records。
- retry 耗尽时返回 schema 合法的 `neutral_stop`。
- fallback 会使该 operator 的连续失败计数 +1。
- 连续失败计数达到阈值前不标记 episode failure；达到 `max_consecutive_failures` 时标记 `llm_failed`，具体比较规则为 `consecutive_failures >= max_consecutive_failures` 并测试。
- 任意成功解析会清零连续失败计数。
- fallback 不使用 `emergency_stop=true`，除非后续安全层另行决定。

## 测试要点（正常 + 边界 + 异常）

- 正常：首次成功、一次 invalid 后成功、一次 timeout 后成功。
- 边界：`max_retries=0`、`max_retries=1`、`max_consecutive_failures=1`、duration default/min/max。
- 异常：一直 invalid、一直 timeout、provider 抛未知异常、retry 后仍返回中文枚举。
- 记录：每次尝试都有 `LLMCallRecord`，包含 observation、messages、provider/model、latency/token usage 或错误摘要。
