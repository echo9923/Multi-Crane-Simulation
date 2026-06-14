# Task 07：Dataset Assembly、Manifest 与 Summary

## 任务目标

把通过质量门禁、完成 split 和 window index 的 episode 组装成正式 dataset 目录，并写出 dataset manifest、dataset summary、quality summary、split manifest、episode/window/file index。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/data/summary.py`。
- 新增 `backend/app/data/dataset_builder.py`。
- 创建 `runs/datasets/{dataset_id}/` 目录结构。
- 根据 `DatasetBuildOptions.copy_mode` 复制、链接或仅索引 source episode。
- 写 `metadata/dataset_manifest.json`。
- 写 `metadata/dataset_summary.json`。
- 写 `metadata/quality_summary.json`。
- 写 `metadata/split_manifest.json`。
- 写 `index/episodes.parquet`、`index/windows.parquet`、`index/files.parquet`。
- 写 `splits/*/episodes.jsonl`。
- 写 quarantine quality reports。
- 统计 dataset_targets 的目标值、实际值和差距。

不做：

- 不生成 STGNN tensors。
- 不把多个 episode 的 Parquet 强制合并成大表；第一版以 index 方式消费原始 run 文件。
- 不修改 source episode 文件。
- 不隐藏 quarantine 数量。

## 接口与数据结构（签名级别）

```python
class DatasetBuilder:
    def __init__(
        self,
        *,
        catalog: DatasetCatalog,
        quality_gate: DatasetQualityGate,
        split_planner: DatasetSplitPlanner,
        window_indexer: DatasetWindowIndexer,
    ) -> None: ...

    def build(
        self,
        *,
        config: DatasetConfig,
        options: DatasetBuildOptions,
    ) -> DatasetBuildResult: ...
```

`DatasetBuildResult` 最低字段：

```python
class DatasetBuildResult(DatasetBaseModel):
    schema_version: str = DATASET_SCHEMA_VERSION
    dataset_id: str
    dataset_dir: Path
    summary_path: Path
    manifest_path: Path
    split_manifest_path: Path
    window_index_path: Path
    num_episodes: int = Field(ge=0)
    num_quarantined: int = Field(ge=0)
    warnings: list[DatasetBuildWarning] = Field(default_factory=list)
```

`dataset_summary.json` 必须至少报告：

```text
dataset_id
created_at
schema_version
git_commit
num_episodes
num_quarantined
split_counts
window_counts
risk_distribution
task_completion_rate
near_miss_count
collision_count
operator_profile_distribution
scenario_class_distribution
num_cranes_distribution
targets
target_gaps
warnings
source_roots
copy_mode
```

## 前置依赖

- Task 01 schema。
- Task 02 source catalog。
- Task 04 quality gate。
- Task 05 split planner。
- Task 06 window indexer。
- PyArrow。

## 验收标准（具体、可测试）

- 构建后 dataset 目录包含 overview 中列出的 metadata/index/splits 关键文件。
- `metadata/dataset_summary.json` 可被 `DatasetSummary.model_validate()`。
- `index/windows.parquet` 可被 PyArrow 读取。
- `splits/train/episodes.jsonl` 等文件中的 episode 与 split_manifest 一致。
- quarantine episode 不出现在正式 split。
- target gaps 报告 high/near_miss/collision 或任务/operator 目标差距。
- manifest 记录 git commit；无法读取 git commit 时写 `null` 并 warning。
- manifest/summary/index 静态扫描不包含完整 secret。

## 测试要点（正常 + 边界 + 异常）

正常：

- 3 个合格 episode 构建一个小 dataset。
- 1 个 failed quality episode 进入 quarantine。
- `copy_mode="index_only"` 不复制原始文件，但 index 中 source path 完整。

边界：

- 空 source roots 构建失败并给明确错误。
- 只有 warning quality episode，仍可构建但 summary 有 warning。
- high risk target 未达标，构建成功但 summary 有 `DATASET_W_RISK_TARGET_MISSED`。

异常：

- 输出目录不可写。
- 写 summary 成功前发生错误，不返回成功 result。
- split leakage validator 抛错时不写成功 manifest。
- source path 消失。

## 依赖关系

依赖 Task 01、Task 02、Task 04、Task 05、Task 06。Task 08、Task 09 依赖本任务。
