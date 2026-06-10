# Task 01：配置 Schema 与领域对象

## 任务目标

建立模块 A 的 Pydantic 配置模型，作为后端配置 schema 的唯一事实源。实现后，系统应能把原始 YAML 解析为强类型对象，并为后续 JSON Schema、OpenAPI、前端类型和数据校验提供统一来源。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.6.1`、`0.7.2`、`0.8.1` 和 `模块 A`。

## 任务范围

本任务只定义配置对象、枚举和字段校验：

- `RawScenarioConfig -> ScenarioConfig -> ResolvedScenarioConfig`
- `RawExperimentConfig -> ExperimentConfig -> ResolvedExperimentConfig`
- `RawDatasetConfig -> DatasetConfig`

本任务不实现：

- 自动布局采样
- 任务点生成
- operator 运行逻辑
- LLM provider 调用
- 物理仿真
- 数据集窗口切片

这些行为只在 schema 中保留配置入口，具体实现由模块 B/D/G/C/O/P 等后续模块完成。

## 技术实现

建议创建或预留以下代码文件：

```text
backend/app/schemas/enums.py
backend/app/schemas/config.py
```

`schemas/enums.py` 集中定义配置相关枚举，至少覆盖：

- `LayoutMode`: `auto` / `manual`
- `TaskAssignmentMode`: `per_crane_queue`
- `TaskGenerationMode`: `auto` / `manual`
- `TaskType`: `easy_task` / `overlap_task` / `stress_task`
- `QueueStartMode`: `simultaneous` / `staggered` / `scheduled`
- `WeatherMode`: `schedule` / `constant` / `random`
- `RiskPromptMode`: `R0` / `R1`
- `SafetyMode`: `S0` / `S1` / `S2` / `S3`
- `RuntimeMode`: `offline_batch` / `offline_replay` / `interactive_server`
- `LLMProviderName`: `deepseek` / `minimax` / `mock` / `replay`
- `OperatorProfile`: `normal` / `conservative` / `aggressive` / `novice` / `fatigued`

`schemas/config.py` 定义三类顶层配置。

`ScenarioConfig` 必须覆盖这些主要区块：

```text
schema_version
scenario_id
seed
site
load_types
crane_models
layout
cranes
tasks
weather
risk
```

`site` 至少表达：

- `coordinate_system`
- `boundary`
- `forbidden_zones`
- `material_zones`
- `work_zones`
- `forbidden_zone_policy`

`layout` 至少表达：

- `mode`
- `num_cranes`
- `overlap_level`
- `height_strategy`
- `coverage_target`
- `slew_mode_default`
- `max_sampling_attempts`

`cranes` 只在 `layout.mode=manual` 时作为手写布局输入。模块 A 校验字段结构，不判断复杂几何可行性；manual crane 越界、落入 forbidden zone 等几何判断由模块 B 的 manual layout validator 负责。

`ExperimentConfig` 必须覆盖这些主要区块：

```text
schema_version
experiment_id
scenario_ref
seed
sim
risk_prompt_mode
safety_mode
runtime
operators
llm
output
```

`llm` 必须能表达：

- `enabled`
- `provider`
- `model`
- `base_url`
- `api_key`
- `api_key_env`
- `temperature`
- `timeout_s`
- `max_retries`
- `max_consecutive_failures`
- `fallback_policy`
- `command_duration`
- `scheduling`
- `structured_output`
- `context`

`DatasetConfig` 必须覆盖这些主要区块：

```text
schema_version
dataset_id
run_root
sources
split
windows
export
```

## 输入与输出

输入：

- 原始 YAML 字典
- CLI/API 参数覆盖后的原始字典

输出：

- `ScenarioConfig`
- `ExperimentConfig`
- `DatasetConfig`
- Pydantic validation errors
- 可导出的 JSON Schema

## 拥有对象

模块 A 拥有并写入：

- `ScenarioConfig`
- `ExperimentConfig`
- `DatasetConfig`

模块 A 只定义或接收接口，不拥有：

- `CraneModelSpec`
- `CraneConfig`
- `Task`
- `CraneState`
- `Observation`
- `ParsedCommand`
- `ExecutedCommand`
- `OfflineRiskLabel`

## 边界规则

- `ScenarioConfig` 不得包含完整 LLM API key。
- `ExperimentConfig` 可以接收 `api_key` 和 `api_key_env`，但不得决定落盘脱敏格式；脱敏规则在 Task 05 实现。
- 所有顶层配置必须包含 `schema_version`。
- nullable 字段必须明确为 `null`，不得用空字符串表示缺失。
- 枚举值必须集中定义，不得在业务代码中重复写字符串集合。
- 自动布局、任务生成、风险计算只做配置结构校验，不执行模块 B/D/H/K 的业务逻辑。

## 错误处理

schema 校验失败必须能映射到稳定错误码：

- scenario 校验失败映射为 `CFG_E_001`
- experiment 校验失败映射为 `CFG_E_002`
- dataset 校验失败使用模块 A dataset config error，若实现时尚未新增专用错误码，可先归入配置 startup error 并在错误对象中标注 `config_kind=dataset`

每个 validation error 至少提供：

- 字段路径
- 原始来源文件
- 错误消息
- 可读修复建议

## 测试用例

- 有效 `scenario.yaml` 可以解析为 `ScenarioConfig`。
- 有效 `experiment.yaml` 可以解析为 `ExperimentConfig`。
- 有效 `dataset.yaml` 可以解析为 `DatasetConfig`。
- 缺失 `schema_version` 时失败。
- `layout.mode` 不是 `auto` 或 `manual` 时失败。
- `risk_prompt_mode` 不是 `R0` 或 `R1` 时失败。
- `safety_mode` 不是 `S0`、`S1`、`S2`、`S3` 时失败。
- `llm.provider` 不是 `deepseek`、`minimax`、`mock`、`replay` 时失败。
- `layout.mode=manual` 且 `cranes` 字段缺失时给出明确配置错误。
- `layout.mode=auto` 时允许 `cranes` 缺失。

## 验收标准

- 三类配置对象能独立解析和校验。
- 所有配置对象都包含 `schema_version`。
- 主要枚举集中定义在 schema 层。
- 主要配置区块覆盖 v0.4 方案中模块 A 的示例字段。
- validation error 可以转换为模块 A startup error。
- schema 层没有调用物理、布局、任务、LLM 或风险模块。
