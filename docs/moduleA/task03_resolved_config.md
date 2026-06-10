# Task 03：ResolvedConfig、默认值追踪与配置 Hash

## 任务目标

生成模块 A 的主要权威输出 `ResolvedConfig`。它必须包含所有运行所需的配置、默认值、种子、provider 元信息和后续模块需要读取的 resolved 字段，并提供稳定的 `resolved_config_hash` 用于复现、replay 和数据质量检查。

本任务接收 Task 01/Task 02 产出的 typed config，不重新读取 YAML，不重新应用 CLI/API override，也不重复定义基础字段 schema。它负责把 typed config 落定为可运行、可追溯、可 hash 的 resolved 配置。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.7.2`、`0.7.9`、`0.8.8`、`15.2` 和 `模块 A`。

## 任务范围

本任务实现：

- `ScenarioConfig + ExperimentConfig + optional DatasetConfig` 到 `ResolvedConfig`
- 默认值落定与默认值来源追踪
- seed 解析与写入
- provider/operator 配置 resolve
- persisted-safe provider 摘要接入
- manual layout 输入的保留
- auto layout 输出槽位预留
- `resolved_config_hash`
- deterministic serialization

本任务不实现：

- 自动布局采样
- 任务队列生成
- operator 真正分配运行实例
- 环境变量中的真实 key 读取和 key 脱敏规则
- replay 执行命令比对
- episode 调度

## 技术实现

建议创建或预留以下代码文件：

```text
backend/app/core/config_resolver.py
backend/app/core/config_hash.py
backend/app/schemas/config.py
```

`ResolvedConfig` 至少包含：

```text
schema_version
scenario
experiment
dataset_ref 或 dataset
defaults_applied
seeds
layout
tasks
operators
provider
runtime
output
resolved_config_hash
```

`ResolvedConfig` 可包含 `ResolvedScenarioConfig`、`ResolvedExperimentConfig` 等内部子对象，但这些对象由本任务构造，不由 Task 01 生成。

`defaults_applied` 用于追踪默认值来源，建议每条记录包含：

```text
field_path
value
source
reason
```

`seeds` 至少表达：

- scenario seed
- experiment seed
- layout seed
- task seed
- weather seed
- operator assignment seed

如果 v0.4 方案中某个 seed 还未拆成独立字段，resolve 阶段应按稳定规则从 scenario/experiment seed 派生，并记录在 `defaults_applied` 或 `seeds` 诊断中。

`layout` 的处理：

- `layout.mode=manual` 时，保留 `cranes` 手写配置，供模块 B validator 使用。
- `layout.mode=auto` 时，保留 auto layout 参数，并预留 `resolved_cranes=null` 或等价空槽位，等待模块 B 写入 layout resolve 结果。
- 模块 A 不得自行采样塔吊布局。

`operators` 的处理：

- 解析 operator assignment 配置。
- 生成后续模块 G/J 可读取的 resolved operator 配置字段。
- 不创建实际 LLM operator 对象。
- 不调用 provider。

`provider` 的处理：

- 使用 `ExperimentConfig.llm` 中除完整 key 之外的仿真相关字段，例如 provider、model、base_url、temperature、timeout、retry、structured output、context。
- 从 Task 05 接收 persisted-safe provider 摘要，例如 `key_source`、`key_env_name`、`key_masked`。
- 不读取环境变量，不保存完整 `api_key`，不构造 provider HTTP client。
- 真实 provider 缺 key 的启动前校验由 Task 05 负责；本任务只消费其安全结果或错误。

## Hash 规则

`resolved_config_hash` 必须基于 deterministic serialization 计算。

必须包含：

- `schema_version`
- scenario 和 experiment 中影响仿真的字段
- seed
- layout 输入和后续 layout resolve 结果
- task 配置
- weather 配置
- risk/safety mode
- controller 相关配置
- operator 分配配置
- provider/model/temperature 等影响 LLM 输出的字段

必须排除：

- run 创建时间
- 输出目录
- 日志路径
- 临时文件路径
- 完整 `api_key`
- 脱敏后的 `key_masked`
- 不影响仿真的 metadata
- runtime-only secret container 或完整 key 来源值

序列化要求：

- key 排序稳定。
- 浮点数序列化稳定。
- `null` 表示缺失，不用空字符串。
- 字典和列表顺序必须确定。
- hash 算法固定，建议使用 SHA-256。

## 输入与输出

输入：

- `ScenarioConfig`
- `ExperimentConfig`
- optional `DatasetConfig`
- resolved defaults policy

输出：

- `ResolvedConfig`
- `resolved_config_hash`
- defaults diagnostics

## 拥有对象

模块 A 拥有：

- `ResolvedConfig`
- `resolved_config_hash`
- 默认值记录

模块 A 不拥有：

- 模块 B 的最终 `CraneConfig[]` 自动布局生成结果
- 模块 D 的最终 `Task[]`
- 模块 G 的 `RawLLMResponse`
- 模块 L 的 trajectory/visual frame 输出

## 边界规则

- `ResolvedConfig` 生成后视为不可变。
- 后续模块如需补充 layout 或 task resolved 结果，必须通过明确 resolve 阶段接口完成，不得在运行时随意回写。
- hash 不得依赖 run 目录或创建时间。
- hash 不得包含任何形式的完整 API key。
- `resolved_config_hash` 缺失或不可计算时，episode 不得启动。

## 错误处理

- hash 不可计算映射为 `CFG_E_003`。
- 必填 resolved 字段缺失时返回 startup error。
- 默认值无法确定时返回 startup error，并给出字段路径。
- provider 配置缺少必要字段时返回配置 startup error；真实 key 的读取与脱敏细节由 Task 05 处理。
- Task 05 返回真实 provider 缺 key或密钥安全错误时，本任务不得继续生成可启动的 `ResolvedConfig`。

## 测试用例

- 同一 YAML 和同一 override 生成相同 `resolved_config_hash`。
- 只改变 run 输出目录，hash 不变。
- 只改变创建时间，hash 不变。
- 改变 `sim.duration_s`，hash 改变。
- 改变 `risk_prompt_mode`，hash 改变。
- 改变 `safety_mode`，hash 改变。
- 改变 provider model 或 temperature，hash 改变。
- 改变 `key_masked`，hash 不变。
- 改变完整 `api_key` 但不改变 provider/model/temperature 等仿真字段时，hash 不变。
- `layout.mode=manual` 时保留 cranes 输入。
- `layout.mode=auto` 时不生成 cranes，只保留 auto 参数和后续模块槽位。

## 验收标准

- `ResolvedConfig` 包含运行所需配置和 schema version。
- 默认值来源可追溯。
- `resolved_config_hash` 稳定、确定、可复现。
- hash 包含仿真相关字段，排除非仿真 metadata 和密钥。
- `CFG_E_003` 路径可测试。
- 模块 A 不执行自动布局、任务生成、物理仿真或 LLM 调用。
