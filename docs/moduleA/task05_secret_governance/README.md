# Task 05：Provider 配置与密钥治理

## 任务目标

定义并实现模块 A 对 LLM provider 配置和密钥的治理规则。系统必须支持 DeepSeek、MiniMax、mock、replay 四类 provider 配置，同时保证真实 API key 不会被写入 resolved config、日志、metadata、dataset summary 或前端/API payload。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.5.15`、`0.8.12` 和 `模块 A`。

## 任务范围

本任务实现：

- provider 配置解析
- `api_key` 与 `api_key_env` 优先级
- 环境变量 key 读取策略
- key 脱敏
- resolved config 和 metadata 中的安全 provider 摘要
- demo 配置密钥检查
- 真实 provider 缺 key 的启动前校验

本任务不实现：

- DeepSeek HTTP 调用
- MiniMax HTTP 调用
- mock provider 响应生成
- replay command 读取
- LLM retry
- structured output validation

这些行为由模块 G 和 M2/M3 相关任务实现。

## 技术实现

建议创建或预留以下代码文件：

```text
backend/app/core/secret_resolver.py
backend/app/schemas/config.py
```

provider 配置必须支持：

```text
provider
model
base_url
api_key
api_key_env
temperature
timeout_s
max_retries
structured_output.mode
```

`api_key` 和 `api_key_env` 规则：

```text
如果 api_key 非空，优先使用 api_key。
如果 api_key 为空且 api_key_env 非空，从环境变量读取。
如果两者都为空，根据 provider 类型决定是否允许启动。
```

provider 类型规则：

- `deepseek`: 真实 provider，`llm.enabled=true` 时必须能解析到 key。
- `minimax`: 真实 provider，`llm.enabled=true` 时必须能解析到 key。
- `mock`: 不需要真实 key。
- `replay`: 不需要真实 key，但需要 replay 配置在后续模块中校验。

脱敏输出字段：

```text
key_source: inline | env | none
key_env_name: string | null
key_masked: string | null
```

`key_masked` 规则：

- key 长度小于等于 8 时，不显示原文字符，只显示固定掩码。
- key 长度大于 8 时，可保留前 4 位和后 4 位，中间用 `****`。
- `key_masked` 仅用于人类审计，不参与 `resolved_config_hash`。

严禁落盘字段：

```text
api_key
resolved_full_api_key
raw_api_key
secret
token
authorization
```

如果代码中需要把真实 key 传递给模块 G，必须通过运行时 secret container 或 provider runtime config 传递，不写入任何持久化文件。

## 输入与输出

输入：

- `ExperimentConfig.llm`
- 环境变量
- provider 类型
- `llm.enabled`

输出：

- runtime-only secret 值
- persisted-safe provider config
- `key_source`
- `key_masked`
- 密钥诊断信息

## 拥有对象

模块 A 拥有：

- provider 配置解析
- 启动前密钥存在性校验
- provider metadata 脱敏

模块 A 不拥有：

- provider HTTP client
- LLM prompt
- LLM response
- retry 行为
- command parsing

## 边界规则

- `ScenarioConfig` 不得包含 LLM API key。
- demo 配置不得包含真实 `api_key`。
- `resolved_config.yaml` 不得包含完整 key。
- `run_metadata.json` 不得包含完整 key。
- logs、dataset summary、frontend/API payload 不得包含完整 key。
- `api_key` 和 `api_key_env` 同时存在时，使用 `api_key`，并落盘 `key_source=inline`。
- 使用环境变量时，落盘可记录 `key_env_name`，但不得记录环境变量值。

## 错误处理

- `llm.enabled=true` 且 provider 为 `deepseek`，但无法解析 key：startup error。
- `llm.enabled=true` 且 provider 为 `minimax`，但无法解析 key：startup error。
- demo config 中出现疑似真实 inline key：配置安全 error。
- 即将落盘内容包含完整 key：阻止写入并返回配置安全 error。

错误信息应说明：

- provider 名称
- 使用的 key 来源
- 缺失的环境变量名
- 修复建议

## 测试用例

- 只有 `api_key` 时使用 inline key。
- 只有 `api_key_env` 且环境变量存在时使用 env key。
- 两者同时存在时优先 inline key。
- 两者同时存在时落盘 `key_source=inline`。
- `mock` provider 不需要 key。
- `replay` provider 不需要 key。
- `deepseek` 缺 key 时失败。
- `minimax` 缺 key 时失败。
- `key_masked` 不等于原始 key。
- `resolved_config_hash` 不因 `key_masked` 改变而改变。
- `resolved_config.yaml` 和 `run_metadata.json` 中检索不到完整 key。

## 验收标准

- DeepSeek、MiniMax、mock、replay 四类 provider 配置可表达。
- inline key 优先级高于 env key。
- 真实 provider 缺 key 时启动前失败。
- mock/replay 不要求真实 key。
- 所有持久化输出只包含 `key_source` 和 `key_masked`。
- 完整 key 不进入 resolved config、metadata、logs、dataset summary 或前端/API payload。
