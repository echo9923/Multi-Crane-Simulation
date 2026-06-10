# Task 01：配置 Schema 与领域对象

## 任务目标

建立模块 A 的 Pydantic 配置模型，作为后端配置 schema 的唯一事实源。实现后，系统应能把原始 YAML 解析为强类型对象，并为后续 JSON Schema、OpenAPI、前端类型和数据校验提供统一来源。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.6.1`、`0.7.2`、`0.8.1` 和 `模块 A`。

## 任务范围

本任务只定义配置对象、枚举、字段校验和必要的配置输入子模型：

- `RawScenarioConfig -> ScenarioConfig`
- `RawExperimentConfig -> ExperimentConfig`
- `RawDatasetConfig -> DatasetConfig`

`ResolvedScenarioConfig`、`ResolvedExperimentConfig` 和顶层 `ResolvedConfig` 的构造、默认值落定、seed 派生、provider 安全摘要和 `resolved_config_hash` 由 Task 03 实现。Task 01 不生成 resolved 对象，只保证 typed config 能为 Task 03 提供稳定输入。

本任务不实现：

- 自动布局采样
- 任务点生成
- operator 运行逻辑
- LLM provider 调用
- 物理仿真
- 数据集窗口切片
- `ResolvedConfig` 构造、默认值追踪或 hash 计算

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
- `OverlapLevel`: `low` / `medium` / `high`
- `HeightStrategy`: `staggered` / `same_level` / `mixed`
- `CoverageTarget`: `balanced` / `wide_coverage` / `dense_overlap`
- `SlewMode`: `continuous` / `limited`
- `ForbiddenZonePolicyMode`: `task_only` / `hard`
- `PriorityLevel`: `low` / `medium` / `high`
- `OperatorAssignmentMode`: `random` / `manual` / `per_crane`
- `LLMFallbackPolicy`: `neutral_stop`
- `LLMSchedulingMode`: `offline_wait` / `realtime_stale`
- `StructuredOutputMode`: `json_object` / `json_schema`
- `LLMHistoryMode`: `none` / `short` / `long`
- `SummarizerMode`: `none` / `rule` / `llm`
- `SummarizerProviderMode`: `same_as_operator` / `explicit`
- `VisibilityLevel`: `low` / `medium` / `high`

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

为避免和模块 B/D 的权威运行对象混淆，Task 01 中的子模型命名应体现其配置输入属性：

- `CraneModelConfigInput`：YAML 中的塔吊型号配置输入，不等同于模块 B 的 `CraneModelSpec`。
- `ManualCraneLayoutInput`：`layout.mode=manual` 时的手写布局输入，不等同于模块 B 的最终 `CraneConfig`。
- `TaskGenerationConfig`：任务生成策略配置，不等同于模块 D 的运行时 `Task`。
- `ManualTaskInput`：若后续支持 `tasks.generation_mode=manual`，只表达任务输入模板，不包含 `Task.status`、运行阶段或事件字段。

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

建议至少拆分以下子模型，避免在单个 Pydantic model 中混合过多职责：

```text
ScenarioConfig:
  SiteConfig
  BoundaryConfig
  ZoneConfig / BoxZoneConfig / PolygonZoneConfig
  ForbiddenZonePolicyConfig
  LoadTypeConfig
  CraneModelConfigInput
  LayoutConfig
  ManualCraneLayoutInput
  TaskGenerationConfig
  QueuePolicyConfig
  DeadlinePolicyConfig
  TaskStateMachineConfig
  WeatherConfig
  RiskConfig

ExperimentConfig:
  SimConfig
  RuntimeConfig
  OperatorAssignmentConfig
  LLMConfig
  LLMCommandDurationConfig
  LLMSchedulingConfig
  StructuredOutputConfig
  LLMContextConfig
  OutputConfig

DatasetConfig:
  DatasetSourceConfig
  DatasetSplitConfig
  DatasetWindowConfig
  DatasetExportConfig
```

## 输入与输出

输入：

- 原始 YAML 字典
- 或由 Task 02 应用 CLI/API override 后得到的最终原始字典

Task 01 不读取 YAML 文件、不拆分 `configs/demo.yaml`、不应用 CLI/API override，也不附加 `source_file`。这些来源与合并职责属于 Task 02。

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

Task 01 可拥有 `CraneModelConfigInput`、`ManualCraneLayoutInput`、`TaskGenerationConfig` 等配置输入模型；这些模型只是后续模块的输入合同，不是后续模块的权威运行对象。

## 边界规则

- `ScenarioConfig` 不得包含完整 LLM API key。
- `ExperimentConfig` 可以接收 `api_key` 和 `api_key_env`，但不得决定落盘脱敏格式；脱敏规则在 Task 05 实现。`api_key` 字段应使用 `SecretStr` 或等价安全字段，避免 repr、日志或默认 dump 裸露完整值。
- 所有顶层配置必须包含 `schema_version`。
- nullable 字段必须明确为 `null`，不得用空字符串表示缺失。
- 枚举值必须集中定义，不得在业务代码中重复写字符串集合。
- 自动布局、任务生成、风险计算只做配置结构校验，不执行模块 B/D/H/K 的业务逻辑。

schema 层允许做的静态校验：

- required 字段存在。
- enum 合法。
- 数值基础范围合法，例如 `dt > 0`、`duration_s > 0`、`num_cranes > 0`。
- 二元 range 长度为 2，且 `min <= max`。
- `boundary` 满足 `x_min < x_max`、`y_min < y_max`、`z_min < z_max`。
- distribution 权重为非负数，并明确要求总和约等于 1；若未来改为 resolve 阶段归一化，必须同步修订本任务。
- `layout.mode=manual` 时 `cranes` 必填。
- `layout.mode=auto` 时允许 `cranes` 缺失。

schema 层不得做的运行时或跨模块判断：

- 不采样自动布局。
- 不判断塔吊是否覆盖所有 zone。
- 不判断 manual crane 是否越界或落入 forbidden zone。
- 不生成最终 `CraneConfig[]`。
- 不生成最终 `Task[]`。
- 不判断 pickup/dropoff 是否可达或是否超载。
- 不计算 online/offline risk。

## 错误处理

schema 校验失败必须能映射到稳定错误码：

- scenario 校验失败映射为 `CFG_E_001`
- experiment 校验失败映射为 `CFG_E_002`
- dataset 校验失败使用模块 A dataset config error，若实现时尚未新增专用错误码，可先归入配置 startup error 并在错误对象中标注 `config_kind=dataset`

Task 01 的 Pydantic validation error 至少应保留：

- 字段路径
- 错误消息

`source_file`、`config_kind`、错误码、可读修复建议和 startup error 对象由 Task 02/Task 06 在错误转换时附加。

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
- `api_key` 使用安全字段，默认 repr 或 dump 不裸露完整 key。
- `tasks.task_type_distribution` 权重为负或总和明显不为 1 时失败。
- `site.boundary` 的 min/max 关系非法时失败。

## 验收标准

- 三类配置对象能独立解析和校验。
- 所有配置对象都包含 `schema_version`。
- 主要枚举集中定义在 schema 层。
- 配置输入子模型不会和模块 B/D/G 的权威运行对象混用。
- 主要配置区块覆盖 v0.4 方案中模块 A 的示例字段。
- validation error 可以转换为模块 A startup error。
- schema 层没有调用物理、布局、任务、LLM 或风险模块。
