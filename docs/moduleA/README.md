# 模块 A：场景配置与实验管理模块任务索引

## 模块目标

模块 A 负责把原始 YAML、CLI 参数和 API 参数转换为稳定、可验证、可追溯的配置对象，并创建运行目录与运行元数据。它是后续布局、任务、仿真、LLM、风险和数据导出模块的配置入口。

权威来源为项目根目录下的 `群塔LLM仿真系统开发方案_v0.4_完整版.md`。若本目录文档与该方案冲突，以方案中 `0.6`、`0.7`、`0.8` 和 `模块 A` 的合同约定为准，并同步修订本目录文档。

## 模块边界

模块 A 的输入：

- `scenario.yaml`
- `experiment.yaml`
- `dataset.yaml`
- 可选的 `configs/demo.yaml` 单文件便捷入口
- CLI 或 API 参数覆盖项

模块 A 的输出：

- `ScenarioConfig`
- `ExperimentConfig`
- `DatasetConfig`
- `ResolvedConfig`
- `resolved_config_hash`
- run workspace
- `config/resolved_config.yaml`
- `metadata/run_metadata.json`

模块 A 不允许做的事情：

- 不生成或积分 `CraneState`
- 不生成物理轨迹
- 不调用真实 LLM
- 不生成任务轨迹或任务状态机结果
- 不计算 online/offline 风险标签
- 不把完整 `api_key` 写入任何落盘产物、日志、summary 或前端/API payload

## 任务顺序

| 顺序 | 文档 | 目标 |
|---|---|---|
| 1 | [task01_config_schema](task01_config_schema.md) | 定义配置 Pydantic schema、枚举、对象层级和校验边界 |
| 2 | [task02_config_loading](task02_config_loading.md) | 定义 YAML 加载、单文件入口拆分、参数覆盖和安全路径处理 |
| 3 | [task03_resolved_config](task03_resolved_config.md) | 定义 `ResolvedConfig`、默认值追踪和 `resolved_config_hash` |
| 4 | [task04_run_workspace](task04_run_workspace.md) | 定义 run 目录结构、resolved config 落盘和运行元数据 |
| 5 | [task05_secret_governance](task05_secret_governance.md) | 定义 provider 配置、密钥优先级、脱敏和密钥泄漏防护 |
| 6 | [task06_validation_errors](task06_validation_errors.md) | 定义配置启动错误、错误对象和 no-startup 规则 |
| 7 | [task07_tests_and_acceptance](task07_tests_and_acceptance.md) | 定义模块 A 的测试清单与验收标准 |

## 全局实现约束

- 后端 Pydantic model 是领域对象 schema 的唯一事实源。
- 所有配置对象和落盘对象必须包含 `schema_version`。
- 配置错误必须显式分类为 startup error，不得只写日志后继续运行。
- `ScenarioConfig` 不得包含 LLM API key。
- `ExperimentConfig` 可声明 provider、model、`api_key`、`api_key_env`，但落盘必须脱敏。
- `ResolvedConfig` 运行后视为不可变，后续模块只能读取，不得回写。
- `DatasetConfig` 可由模块 A 解析，但批量生成、划分和窗口切片由模块 O/P 实现。
- `layout.mode=auto` 和任务生成策略在模块 A 只做 schema 与形状校验，实际自动布局与任务生成由模块 B/D 实现。

## 最小交付结果

完成本模块文档后，后续实现者应能按任务顺序实现：

1. 配置 schema 与枚举。
2. YAML 加载和参数覆盖。
3. deterministic resolve 与 hash。
4. run workspace 和 metadata。
5. provider 密钥治理。
6. startup error 映射。
7. 单元测试、合同测试和验收检查。
