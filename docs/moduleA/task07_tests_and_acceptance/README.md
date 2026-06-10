# Task 07：模块 A 测试与验收

## 任务目标

为模块 A 建立可执行的测试清单和验收标准，确保配置 schema、加载、resolve、run workspace、密钥治理和错误处理满足 v0.4 合同。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.8.13`、`0.8.14`、`模块 A` 和 `15.2`。

## 任务范围

本任务定义：

- 单元测试
- 合同测试
- 安全测试
- 文档验收
- 模块 A 退出条件

本任务不要求实现：

- M0 物理仿真验收
- controller 测试
- recorder 导出测试
- LLM provider 真实调用测试
- 前端 visual smoke

这些测试属于 M0-M5 后续阶段。

## 输入与输出

输入：

- Task 01 至 Task 06 的实现结果
- 配置 fixture
- 模块 A 错误对象
- run workspace 示例输出
- resolved config 示例输出

输出：

- 模块 A 单元测试
- 模块 A 合同测试
- 模块 A 安全测试
- 文档验收结果
- 模块 A 退出条件报告

## 技术实现

建议创建或预留以下测试文件：

```text
backend/app/tests/test_config_schema.py
backend/app/tests/test_config_loader.py
backend/app/tests/test_resolved_config.py
backend/app/tests/test_run_workspace.py
backend/app/tests/test_secret_governance.py
backend/app/tests/test_config_errors.py
```

测试数据建议放在：

```text
backend/app/tests/fixtures/configs/
  scenario_valid.yaml
  experiment_valid.yaml
  dataset_valid.yaml
  demo_valid.yaml
  scenario_missing_required.yaml
  experiment_invalid_enum.yaml
```

## 必测场景

schema 测试：

- valid scenario YAML loads successfully。
- valid experiment YAML loads successfully。
- valid dataset YAML loads successfully。
- missing `schema_version` fails。
- invalid enum fails。
- `layout.mode=manual` 时缺少 `cranes` 给出明确错误。
- `layout.mode=auto` 时允许不提供 `cranes`。

加载测试：

- separate `scenario.yaml`、`experiment.yaml`、`dataset.yaml` 可以加载。
- single-file `configs/demo.yaml` 可以拆分为 typed config。
- demo 入口不会向后传递混合配置对象。
- CLI/API overrides apply deterministically。
- 未传入 override 不会覆盖 YAML。
- 路径穿越被拒绝。

resolved config 测试：

- 同一输入生成稳定 `resolved_config_hash`。
- hash excludes run path。
- hash excludes created timestamp。
- hash excludes `key_masked`。
- 改变 sim/risk/safety/operator/provider 关键字段会改变 hash。
- `layout.mode=manual` 保留 cranes 输入。
- `layout.mode=auto` 不执行自动布局。

run workspace 测试：

- 创建标准目录结构。
- 写入 `config/resolved_config.yaml`。
- 写入 `metadata/run_metadata.json`。
- 连续运行不覆盖已有目录。
- metadata 包含 git/package/env 摘要字段。
- 所有输出路径位于 run workspace 内。

密钥治理测试：

- inline `api_key` wins over `api_key_env`。
- env key can be resolved from environment。
- `deepseek` 缺 key 时 startup error。
- `minimax` 缺 key 时 startup error。
- `mock` 不需要 key。
- `replay` 不需要 key。
- full key is never persisted。
- `key_masked` is persisted。

错误测试：

- scenario validation failure -> `CFG_E_001`。
- experiment validation failure -> `CFG_E_002`。
- hash failure -> `CFG_E_003`。
- startup error prevents episode startup。
- error object includes required fields。
- error object does not contain full API key。

## 推荐命令

模块 A 实现完成后运行：

```bash
pytest backend/app/tests/test_config_schema.py
pytest backend/app/tests/test_config_loader.py
pytest backend/app/tests/test_resolved_config.py
pytest backend/app/tests/test_run_workspace.py
pytest backend/app/tests/test_secret_governance.py
pytest backend/app/tests/test_config_errors.py
```

如果测试目录已经统一组织，也可以运行：

```bash
pytest backend/app/tests -k "config or secret or workspace"
```

## 文档验收命令

文档创建完成后运行：

```bash
find docs/moduleA -maxdepth 2 -name "README.md" -print | sort
```

期望看到：

```text
docs/moduleA/README.md
docs/moduleA/task01_config_schema/README.md
docs/moduleA/task02_config_loading/README.md
docs/moduleA/task03_resolved_config/README.md
docs/moduleA/task04_run_workspace/README.md
docs/moduleA/task05_secret_governance/README.md
docs/moduleA/task06_validation_errors/README.md
docs/moduleA/task07_tests_and_acceptance/README.md
```

检查无未完成标记：

```bash
rg -n "<unfinished-marker-regex>" docs/moduleA
```

期望无输出。

检查关键合同字段：

```bash
rg -n "api_key|key_masked|resolved_config_hash|CFG_E_001|CFG_E_002|CFG_E_003|ScenarioConfig|ExperimentConfig|DatasetConfig|ResolvedConfig" docs/moduleA
```

期望能在对应任务文档中检索到关键合同。

## 验收标准

- 能读取并校验 YAML 配置。
- 缺失必要字段时给出明确错误。
- 所有默认值可追溯。
- 每次运行自动生成独立 run 目录。
- 同一输入生成稳定 `resolved_config_hash`。
- `layout.mode=auto` 和 `layout.mode=manual` 都能在配置层表达。
- 不硬编码塔吊数量，按配置表达 N 台塔吊。
- 示例配置目标至少能覆盖 3 台塔吊、每台至少 5 个任务。
- provider 配置支持 DeepSeek、MiniMax、mock、replay。
- 支持直接配置 `api_key` 或通过 `api_key_env` 读取 key。
- 所有运行产物只保存脱敏 key。
- 配置错误作为 startup error 阻止 episode 启动。

## 退出条件

模块 A 可进入后续 M0 实现的条件：

- Task 01 至 Task 06 的实现测试全部通过。
- 文档验收命令通过。
- `resolved_config.yaml` 示例输出不含完整 API key。
- `run_metadata.json` 示例输出不含完整 API key。
- 配置错误码 `CFG_E_001`、`CFG_E_002`、`CFG_E_003` 都有测试覆盖。
- 实现没有调用物理、任务、LLM、风险或前端模块的运行时逻辑。
