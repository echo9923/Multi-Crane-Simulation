# Task 06：配置错误、Startup Error 与诊断对象

## 任务目标

建立模块 A 的配置错误体系。所有配置加载、schema 校验、resolve 和 hash 失败都必须转换为稳定、可读、可测试的 startup error，并阻止 episode 启动。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.7.5`、`0.8.3`、`0.8.4` 和 `模块 A`。

## 任务范围

本任务实现：

- 配置错误码映射
- 配置错误对象 schema
- Pydantic validation error 转换
- startup no-run 行为
- layout/task 配置形状错误的模块 A 边界说明

本任务不实现：

- API HTTP 422 统一响应
- episode runtime failure
- task failed
- replay mismatch
- data quality failure

这些错误由模块 M、J、D、REPLAY、DATA 等后续模块处理。

## 技术实现

建议创建或预留以下代码文件：

```text
backend/app/schemas/errors.py
backend/app/core/config_errors.py
```

模块 A 最低错误码：

```text
CFG_E_001 scenario.yaml schema 校验失败 -> startup_error，不启动
CFG_E_002 experiment.yaml schema 校验失败 -> startup_error，不启动
CFG_E_003 resolved_config_hash 缺失或不可计算 -> startup_error，不启动
```

错误对象字段：

```text
schema_version
error_code
severity
category
message
field_path
source_file
hint
details
```

字段说明：

- `schema_version`: 错误对象 schema 版本。
- `error_code`: 稳定机器码，例如 `CFG_E_001`。
- `severity`: `E` / `W` / `D`。
- `category`: `startup_error`、`warning` 或 `diagnostic`。
- `message`: 面向人类的错误说明。
- `field_path`: 例如 `tasks.queue_policy.start_mode`。
- `source_file`: 原始 YAML 文件路径。
- `hint`: 修复建议。
- `details`: Pydantic 原始错误、非法值摘要或其他诊断。

错误消息语言：

- 主体可以使用中文，便于项目开发者阅读。
- 字段名、枚举值和错误码保持英文稳定。
- 不要把错误码翻译成中文。

## 输入与输出

输入：

- YAML 加载错误
- Pydantic validation error
- path security error
- resolve error
- hash error

输出：

- config error object
- startup failure result
- diagnostic report

## 拥有对象

模块 A 拥有：

- `CFG_*` 配置错误
- 配置 startup error object
- 配置诊断信息

模块 A 不拥有：

- `LAY_*` 自动布局失败的最终判断
- `TASK_*` 任务生成失败的最终判断
- `LLM_*` provider runtime failure
- `PHYS_*` 物理状态错误
- `REC_*` recorder 写入错误

## 边界规则

- 模块 A 可检查 layout/task 配置字段是否存在、类型是否正确、枚举是否合法。
- 模块 A 不运行自动布局，因此不产生 `LAY_E_001` 的最终采样失败。
- 模块 A 不生成任务点，因此不产生 `TASK_E_001` 或 `TASK_E_002` 的最终可达性/超载判断。
- 配置错误发生后不得启动 episode。
- 错误不得只写日志后继续运行。
- 错误对象不得包含完整 API key。

## 错误处理

场景示例：

- `scenario.yaml` 缺失 `site.boundary`：返回 `CFG_E_001`。
- `experiment.yaml` 中 `safety_mode=S9`：返回 `CFG_E_002`。
- `resolved_config_hash` 计算时遇到不可序列化对象：返回 `CFG_E_003`。
- `dataset.yaml` schema 失败：返回配置 startup error，并在 `details.config_kind=dataset` 中标注。
- `layout.mode=auto` 但 `num_cranes` 非法：返回 `CFG_E_001`，不是 `LAY_E_001`。
- `tasks.task_type_distribution` 权重类型非法：返回 `CFG_E_001`，不是 `TASK_E_001`。

## 测试用例

- scenario 缺必填字段映射为 `CFG_E_001`。
- experiment 缺必填字段映射为 `CFG_E_002`。
- hash 不可计算映射为 `CFG_E_003`。
- 错误对象包含 `schema_version`、`error_code`、`message`、`field_path`、`source_file`、`hint`。
- Pydantic 嵌套错误能转换为稳定 field path。
- 配置错误后不会创建或启动 episode。
- 错误对象中不包含完整 API key。

## 验收标准

- 最低三个配置错误码可触发、可测试。
- 所有配置错误都阻止 episode 启动。
- 错误对象字段完整。
- 错误信息可读，并保留稳定机器码。
- 模块 A 不越界执行 layout/task/LLM/physics/risk 的运行时错误判断。
