# Task 03：LLM Provider 抽象

## 任务目标

实现模块 G 的 provider 抽象层，支持 DeepSeek、MiniMax、Mock 和 Replay 四种 provider，并统一返回 `RawLLMResponse` 或历史 `ParsedCommand`。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/sim/llm_provider.py`。
- 定义 `LLMProvider` 基类或 Protocol。
- 定义 `ProviderRequest`、`ProviderResult`、`ProviderTimeoutError`、`ProviderAPIError`、`ReplayCommandNotFoundError`、`ReplayCommandDuplicateError`。
- 实现 `DeepSeekProvider` 和 `MiniMaxProvider` 的请求构造、timeout、structured output 参数、token usage 提取。
- 实现 `MockProvider`，返回确定性合法 JSON 命令，用于无网络开发和单元测试。
- 实现 `ReplayProvider`，读取历史 `ParsedCommand` 记录，按 `source_snapshot_id + crane_id` 匹配。
- 支持 `base_url`、`model`、`api_key`、`api_key_env` 解析后的运行时 secret、`timeout_s`、`max_retries`、`structured_output.mode`。
- 对真实 provider 的 persisted record 只保存 provider/model/base_url/latency/token usage，不保存完整密钥。

不做：

- 不把 `RawLLMResponse` 解析成 `ParsedCommand`，这属于 Task 04。
- 不实现 retry/fallback 策略，provider 只负责一次调用或本地 replay 查找。
- 不做安全审查。
- 不写 `commands.jsonl` 或 `command_replay.jsonl`。
- 不实现总方案 0.7.9 的 `ExecutedCommand` 严格 replay；本任务只做 G 本地 `ParsedCommand` replay。

## 接口与数据结构（签名级别）

```python
class LLMProvider(Protocol):
    provider_name: LLMProviderName

    def generate(self, request: ProviderRequest) -> ProviderResult:
        ...

class ProviderRequest(BaseModel):
    schema_version: str = COMMAND_SCHEMA_VERSION
    observation: Observation
    messages: list[LLMMessage]
    config: LLMConfig
    runtime_secret: ProviderRuntimeSecret | None = None
    attempt_index: int = 0

class ProviderResult(BaseModel):
    schema_version: str = COMMAND_SCHEMA_VERSION
    raw_response: RawLLMResponse | None = None
    replay_command: ParsedCommand | None = None
    latency_ms: float | None = None
    token_usage: TokenUsage | None = None

def create_llm_provider(
    config: LLMConfig,
    *,
    replay_commands: Sequence[ParsedCommand] | None = None,
) -> LLMProvider:
    ...
```

DeepSeek/MiniMax 初版请求风格：

```text
POST {base_url or provider default}/chat/completions
headers: Authorization: Bearer <runtime_secret.full_api_key>
body:
  model
  messages
  temperature
  response_format for StructuredOutputMode.JSON_OBJECT or JSON_SCHEMA
  timeout_s handled by client
```

实际字段可按 provider API 差异封装，但外部接口必须保持 `ProviderRequest -> ProviderResult`。

## 前置依赖

- Task 01 的 `RawLLMResponse`、`ParsedCommand`、`LLMMessage`、`TokenUsage`。
- Task 02 的 `build_operator_messages()`。
- `backend/app/core/secret_resolver.py` 的 `ProviderRuntimeSecret` 和 `REAL_PROVIDERS`。
- `backend/app/schemas/config.py` 的 `LLMConfig`。

## 验收标准（具体、可测试）

- `create_llm_provider()` 能按 `LLMProviderName` 返回正确 provider。
- Mock provider 对同一 observation 输出确定性、schema 合法的 raw JSON 字符串。
- Mock provider 在 active task 下默认输出可解析的低档位任务推进命令；idle task 下默认输出 neutral。
- Replay provider 对匹配的 `source_snapshot_id + crane_id` 返回唯一 `ParsedCommand`，且不调用网络。
- Replay provider 遇到缺失命令抛 `ReplayCommandNotFoundError`。
- Replay provider 遇到重复命令抛 `ReplayCommandDuplicateError`。
- DeepSeek/MiniMax provider 请求中使用 runtime secret，但 `RawLLMResponse.raw_payload` 不保存完整 secret。
- provider timeout 映射为 `ProviderTimeoutError`。
- provider 4xx/5xx 或响应格式异常映射为 `ProviderAPIError`。
- `StructuredOutputMode.JSON_OBJECT` 和 `JSON_SCHEMA` 至少在请求 payload 中可区分。

## 测试要点（正常 + 边界 + 异常）

- 正常：mock provider 生成 raw response；replay provider 找到命令；factory 返回四种 provider。
- 边界：空 visible neighbors、idle observation、R1 safety hint、`api_key_env` 已解析但不落盘。
- 异常：未知 provider、replay missing、replay duplicate、timeout、provider error、真实 provider 响应缺 content。
- 网络隔离：单元测试不调用真实 DeepSeek/MiniMax；用 fake HTTP client 或 monkeypatch 验证请求构造。
