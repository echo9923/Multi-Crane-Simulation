# Task 04：Run Workspace 与运行元数据

## 任务目标

为每次运行创建独立 run workspace，写入 `resolved_config.yaml` 和 `run_metadata.json`，并预创建后续模块需要使用的标准目录。模块 A 只负责目录和元数据，不负责生成轨迹、日志、风险或前端帧内容。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.7.11`、`0.8.12`、`模块 A` 和 `模块 L` 的文件结构约定。

## 任务范围

本任务实现：

- 根据 `output.run_root` 创建运行根目录
- 为每次运行创建独立目录
- 写入 `config/resolved_config.yaml`
- 写入 `metadata/run_metadata.json`
- 预创建 `logs/`、`data/`、`visual/`、`replay/`
- 记录代码版本和运行环境摘要

本任务不实现：

- `trajectories.parquet`
- `pair_risks.parquet`
- `commands.jsonl`
- `events.jsonl`
- `visual/frames.jsonl`
- `replay/command_replay.jsonl`
- `episode_summary.json`

这些文件由模块 L、J、K、G、O 等后续模块写入。

## 技术实现

建议创建或预留以下代码文件：

```text
backend/app/core/run_workspace.py
backend/app/schemas/run_metadata.py
```

默认目录结构：

```text
runs/{experiment_id}/{episode_or_run_id}/
  config/
    resolved_config.yaml
  metadata/
    run_metadata.json
  logs/
  data/
  visual/
  replay/
```

`output.run_root` 默认值为：

```text
runs
```

`episode_or_run_id` 应保证每次运行独立。建议格式：

```text
E{episode_index:04d}
```

或在非 batch 场景使用：

```text
run_{timestamp}_{short_hash}
```

无论采用哪种格式，都必须稳定记录在 `run_metadata.json` 中。

`resolved_config.yaml` 内容：

- 完整 `ResolvedConfig`
- `resolved_config_hash`
- provider 脱敏信息
- 不包含完整 API key

`run_metadata.json` 至少包含：

```text
schema_version
experiment_id
scenario_id
run_id
created_at
git_commit
git_dirty
python_version
package_summary
resolved_config_hash
provider
model
temperature
key_source
key_masked
```

`git_commit` 和 `package_summary` 如果当前环境无法获取，可以为 `null`，但字段必须存在并记录获取失败原因或 diagnostic。

## 输入与输出

输入：

- `ResolvedConfig`
- `output.run_root`
- experiment id
- scenario id
- provider metadata

输出：

- run workspace path
- `config/resolved_config.yaml`
- `metadata/run_metadata.json`
- 标准子目录

## 拥有对象

模块 A 拥有：

- run workspace 创建
- run metadata
- resolved config 落盘

模块 A 不拥有：

- 轨迹数据文件
- 命令日志
- 事件日志
- replay 命令文件
- visual frames
- episode summary 指标

## 边界规则

- 每次运行必须有独立目录，不得覆盖旧 run。
- 所有输出路径必须位于 run workspace 内部。
- 目录创建失败必须中止启动。
- `resolved_config.yaml` 不得包含完整 `api_key`。
- `run_metadata.json` 不得包含完整 `api_key`。
- 模块 A 可以创建空目录，但不得写入后续模块的权威数据文件。

## 错误处理

- run root 路径非法：startup error。
- run workspace 创建失败：startup error。
- `resolved_config.yaml` 写入失败：startup error 或 run failed，启动前必须失败。
- `run_metadata.json` 写入失败：startup error 或 run failed，启动前必须失败。
- 发现完整 key 即将落盘：配置安全 error，阻止写入。

## 测试用例

- 默认 `runs/` 下创建独立 run 目录。
- 自定义 `output.run_root` 创建在允许路径下。
- 创建后包含 `config/`、`metadata/`、`logs/`、`data/`、`visual/`、`replay/`。
- `resolved_config.yaml` 包含 `resolved_config_hash`。
- `run_metadata.json` 包含 experiment id、scenario id、run id。
- 连续两次运行不会覆盖同一目录。
- 非法路径被拒绝。
- metadata 中没有完整 API key。

## 验收标准

- run workspace 结构符合 v0.4 文件约定。
- 每次运行自动生成独立目录。
- resolved config 和 run metadata 都可读取。
- metadata 保存 schema version、hash、代码版本和 provider 摘要。
- 完整密钥不会写入任何 run workspace 文件。
- 模块 A 不写后续模块的数据文件内容。
