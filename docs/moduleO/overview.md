# Module O Overview：实验与数据集生成边界

## 职责

Module O 是仿真系统的数据集构建层。它读取 Module A 的 `DatasetConfig`，驱动或收集多个 episode/run，消费 Module L 已落盘的 episode 文件和 Module K 的离线风险标签，经过质量门禁、quarantine、无泄漏 split、窗口索引和聚合统计后，生成一个可用于论文实验的数据集目录。

O 的核心原则是**只编排、校验、索引、聚合，不改真值**。它可以批量启动 episode、读取 run 目录、判断 episode 是否能进入正式数据集、生成 split 和 sample/window index、汇总 dataset summary；但不得修改原始轨迹、命令、任务状态、在线风险、离线标签或 recorder 文件内容。

## 交互形态

Module O 没有前端页面，也不提供浏览器中的展示元素。它的用户交互入口是命令行和 Module M 的只读 dataset 查询：

```text
python scripts/batch_generate.py --config configs/dataset.yaml
python scripts/build_dataset.py --config configs/dataset.yaml --source-root runs --output-root runs/datasets
GET /datasets
GET /datasets/{dataset_id}/summary
```

如果后续前端 N 展示数据集列表，N 只能通过 M 读取 O 生成的 manifest/summary；N 不直接构建 dataset，也不把 display-only 结果写回 O。

## 数据集目录

第一版建议输出目录：

```text
runs/datasets/{dataset_id}/
  config/
    dataset.yaml
    source_scenarios.json
    source_experiments.json
  metadata/
    dataset_manifest.json
    dataset_summary.json
    quality_summary.json
    split_manifest.json
    generation_report.json
  index/
    episodes.parquet
    windows.parquet
    files.parquet
  splits/
    train/episodes.jsonl
    val/episodes.jsonl
    test/episodes.jsonl
    test_seen_layout/episodes.jsonl
    test_unseen_layout/episodes.jsonl
    test_unseen_num_cranes/episodes.jsonl
    test_high_risk/episodes.jsonl
  episodes/
    {episode_id}/ -> original run directory copy or symlink
  quarantine/
    {episode_id}/
      quality_report.json
```

`episodes/` 可以使用 copy、hardlink 或 symlink 策略，但 manifest 必须记录策略和原始 source path。默认训练消费应通过 `index/` 与 `splits/` 读取，不要求搬运所有 Parquet 到单个大文件。

## 场景类别

O 需要支持 dataset source 中的多场景组合和统计分组，至少覆盖总方案列出的类别：

```text
normal_independent
overlap_safe
crossing_near_miss
multi_crane_yielding
operation_delay
poor_visibility
wind_gust
aggressive_operator
safety_intervention
easy_task
overlap_task
stress_task
mixed_operator_profiles
```

这些类别来自 scenario/experiment metadata 或 episode summary。O 不在构建阶段伪造类别；缺失时记录 warning 并用 `unknown` 参与统计。

## 输入

O 消费：

- A：`DatasetConfig`、`ScenarioConfig`、`ExperimentConfig`、`ResolvedConfig`，以及 `load_dataset_config()`、`load_demo_config()`、`resolve_config()`。
- J/M：本地 runner factory 或 episode service，用于批量生成 episode。O 不拥有仿真主循环。
- L：每个 run 的 `metadata/episode_summary.json`、`visual/episode_manifest.json`、`data/*.parquet`、`logs/*.jsonl`、`replay/command_replay.jsonl`、`config/resolved_config.yaml`。
- K：`pair_risks.parquet` 中的离线标签列，或内存 `OfflineRiskLabel` 对象经 L 写入后的结果。
- Git/runtime：当前 git commit、构建脚本版本、dataset builder 版本、生成时间和命令参数。

## 输出

O 输出：

- `metadata/dataset_manifest.json`：数据集来源、schema version、git commit、配置摘要、文件策略、split 策略、窗口配置。
- `metadata/dataset_summary.json`：数据集聚合指标权威，供 M/P/论文实验读取。
- `metadata/quality_summary.json`：质量门禁通过、warning、失败和 quarantine 统计。
- `metadata/split_manifest.json`：每个 split 的 episode 列表、split 原因、holdout 标记和泄漏检查结果。
- `index/episodes.parquet`：每个 episode 一行的索引。
- `index/windows.parquet`：每个训练窗口一行的通用窗口索引，供 P 转为 STGNN tensors。
- `index/files.parquet`：每个 episode 权威文件路径和 checksum。
- `splits/*/episodes.jsonl`：便于脚本快速读取的 split 清单。
- `quarantine/*/quality_report.json`：被拒绝 episode 的原因和可复查指标。

## 对外接口

建议新增 schema：

```python
DATASET_SCHEMA_VERSION = "1.0"

class DatasetBuildError(RuntimeError): ...
class DatasetBuildWarning(BaseModel): ...
class DatasetBuildOptions(BaseModel): ...
class DatasetEpisodeRecord(BaseModel): ...
class DatasetQualityReport(BaseModel): ...
class DatasetSplitAssignment(BaseModel): ...
class DatasetWindowIndexRow(BaseModel): ...
class DatasetFileRecord(BaseModel): ...
class DatasetManifest(BaseModel): ...
class DatasetSummary(BaseModel): ...
class DatasetBuildResult(BaseModel): ...
```

建议新增服务接口：

```python
class DatasetCatalog:
    def discover_episodes(self, roots: Sequence[Path]) -> list[DatasetEpisodeRecord]: ...
    def read_dataset_summary(self, dataset_id: str) -> DatasetSummary: ...

class DatasetQualityGate:
    def evaluate_episode(self, episode: DatasetEpisodeRecord) -> DatasetQualityReport: ...

class DatasetSplitPlanner:
    def assign(self, episodes: Sequence[DatasetEpisodeRecord]) -> list[DatasetSplitAssignment]: ...

class DatasetWindowIndexer:
    def build(self, assignments: Sequence[DatasetSplitAssignment]) -> list[DatasetWindowIndexRow]: ...

class DatasetBuilder:
    def build(self, config: DatasetConfig, options: DatasetBuildOptions) -> DatasetBuildResult: ...
```

建议文件：

```text
backend/app/schemas/dataset.py
backend/app/data/__init__.py
backend/app/data/catalog.py
backend/app/data/batch_runner.py
backend/app/data/quality.py
backend/app/data/splits.py
backend/app/data/window_index.py
backend/app/data/summary.py
backend/app/data/dataset_builder.py
scripts/build_dataset.py
```

## 对内依赖边界

允许：

- 调用 A 的 dataset config 加载和解析能力。
- 调用 M/J 共享的 runner factory 批量生成 episode。
- 读取 L 产出的 episode 文件并做 schema、时序、完整性和泄漏检查。
- 读取 K 已写入的离线标签列，统计风险比例和窗口标签。
- 复制、链接或索引 episode run 目录。
- 生成 dataset 级 manifest、summary、split、window index。
- 给 M 的 dataset API 提供 `dataset_summary.json` 和可发现目录。

不允许：

- 在 O 中实现物理积分、任务状态机、安全审查、LLM 调用、prompt 构造或风险算法。
- 修改 L 已写入的 episode 原始文件。
- 修改 K 的离线标签真值，或把在线风险当成离线标签。
- 按 window 随机划分 train/val/test。
- 让 quarantine episode 默认进入训练 split。
- 把完整 secret 写入任何 dataset 输出。
- 在 O 中实现 PyTorch Dataset 或模型训练逻辑；P 消费 `windows.parquet` 和 source files 后再转换。

## 失败边界

| 失败 | 默认处理 |
| --- | --- |
| dataset.yaml schema 失败 | 构建失败，`DATASET_E_CONFIG_INVALID` |
| source run root 不存在 | 构建失败或 warning，取决于 source 是否 required |
| episode 必需文件缺失 | 该 episode 进入 quarantine，记录 `DATASET_Q_MISSING_FILE` |
| Parquet/JSONL/schema 读取失败 | 该 episode 进入 quarantine |
| frame/time 非单调或不完整 | 该 episode 进入 quarantine |
| offline label 缺失 | 需要训练标签的构建失败或该 episode quarantine |
| split 出现 episode 泄漏 | 整个 dataset build failed |
| 高风险比例未达到 target | dataset build warning，summary 报告差距；不得伪造样本 |
| 可用 episode 数不足 | build failed 或 warning，取决于 `min_episodes_required` 配置 |
| 写 dataset manifest/summary 失败 | build failed，不返回成功结果 |

## 权威来源

若本文档与根目录 `目标.md` 或 `群塔LLM仿真系统开发方案_v0.4_完整版.md` 冲突，以 `目标.md` 的硬性阶段闸口、总方案 `0.8.9`、`0.8.10`、`模块 O`、`15.7 M5`，以及当前 A/K/L/M 的已实现 schema 合同为准，并同步修订本文档。
