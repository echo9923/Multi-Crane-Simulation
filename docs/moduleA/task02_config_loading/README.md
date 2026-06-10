# Task 02：配置加载、入口拆分与参数覆盖

## 任务目标

实现配置加载入口，把 YAML 文件和 CLI/API 参数转换为 Task 01 定义的强类型配置对象。加载器必须支持三文件分层配置，也允许 `configs/demo.yaml` 作为便捷入口，但内部不得长期使用混合配置对象。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.6.1`、`0.7.3`、`0.8.1` 和 `模块 A`。

## 任务范围

本任务实现：

- 读取 `scenario.yaml`
- 读取 `experiment.yaml`
- 读取 `dataset.yaml`
- 读取可选单文件 `configs/demo.yaml`
- 将单文件入口拆分为 `ScenarioConfig`、`ExperimentConfig`、`DatasetConfig`
- 应用 CLI/API 覆盖项
- 路径规范化和路径安全检查

本任务不实现：

- `ResolvedConfig` hash
- run workspace 创建
- 密钥脱敏落盘
- 自动布局生成
- 任务生成
- episode 调度

## 技术实现

建议创建或预留以下代码文件：

```text
backend/app/core/config_loader.py
backend/app/core/path_utils.py
backend/app/schemas/config.py
```

加载器应提供清晰入口：

```text
load_scenario_config(path, overrides=None) -> ScenarioConfig
load_experiment_config(path, overrides=None) -> ExperimentConfig
load_dataset_config(path, overrides=None) -> DatasetConfig
load_demo_config(path, overrides=None) -> tuple[ScenarioConfig, ExperimentConfig | None, DatasetConfig | None]
```

单文件 `configs/demo.yaml` 的处理规则：

1. 读取原始 YAML。
2. 按顶层字段拆分为 scenario、experiment、dataset 三类原始字典。
3. 分别进入对应 Pydantic model。
4. 加载完成后只向后传递 typed config 对象。
5. 不允许后续模块依赖 demo 文件中的混合字典结构。

参数覆盖优先级：

```text
Pydantic 默认值 < 原始 YAML 值 < 显式 CLI/API override < resolve 阶段默认值
```

说明：

- Pydantic 默认值只用于字段级基础默认。
- YAML 是主要配置来源。
- CLI/API 覆盖必须是显式传入值，不能把未传参数误当作覆盖。
- resolve 阶段默认值在 Task 03 处理，用于生成可追溯的 resolved config。

路径处理规则：

- `scenario_ref`、`replay_file`、`run_root` 等路径必须规范化。
- 相对路径以项目根目录或调用方声明的 config root 为基准。
- 输出路径必须限制在 run workspace 内部。
- 禁止 `..` 路径穿越到不应写入的位置。
- 读取配置文件时，错误消息必须包含来源路径。

## 输入与输出

输入：

- YAML 文件路径
- 原始 YAML 字典
- CLI/API override 字典
- config root

输出：

- `ScenarioConfig`
- `ExperimentConfig`
- `DatasetConfig`
- 加载诊断信息
- validation error 列表

## 拥有对象

模块 A 加载器拥有：

- 原始配置读取结果
- config source metadata
- typed config object

加载器不得写入：

- `CraneState`
- `Task.status`
- run output data
- logs/commands
- risk labels

## 边界规则

- `configs/demo.yaml` 只是便捷入口，不是新的长期配置类型。
- 加载器不得在内存中保留并传递混合配置对象给后续模块。
- CLI/API 参数只能覆盖配置字段，不得触发仿真动作。
- 路径规范化只负责安全和一致性，不负责创建 run 目录；run 目录由 Task 04 负责。
- 加载器不读取环境变量中的真实 key；密钥解析和脱敏由 Task 05 负责。

## 错误处理

加载失败应分类为 startup error：

- YAML 文件不存在：配置加载 startup error。
- YAML 语法错误：配置加载 startup error。
- schema 校验失败：交给 Task 06 映射为 `CFG_E_001` 或 `CFG_E_002`。
- 路径穿越：配置安全 startup error。
- demo 单文件缺失 scenario 部分：scenario config startup error。

错误对象必须包含：

- `source_file`
- `field_path`
- `message`
- `hint`

## 测试用例

- 分别加载独立 `scenario.yaml`、`experiment.yaml`、`dataset.yaml`。
- 加载单文件 `configs/demo.yaml` 并拆分为 typed config。
- CLI override 能覆盖 `experiment.sim.duration_s`。
- 未传入的 CLI 参数不会覆盖 YAML。
- 相同 YAML 和相同 override 产生相同 typed config。
- `../outside.yaml` 这类非法写路径被拒绝。
- YAML 语法错误返回带 `source_file` 的错误。

## 验收标准

- 三文件分层配置可用。
- 单文件 demo 入口可用，但不会向后传播混合对象。
- 覆盖优先级清晰、可测试、确定性稳定。
- 路径安全规则明确实现。
- 错误信息能指向文件和字段。
- 加载器不创建物理状态、不启动 episode、不调用 LLM。
