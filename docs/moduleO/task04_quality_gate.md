# Task 04：Quality Gate 与 Quarantine

## 任务目标

实现 episode 级数据质量门禁。每个 episode 结束后或 dataset build 前必须被校验；未通过的 episode 进入 quarantine，默认不得进入正式 train/val/test split。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/data/quality.py`。
- 针对 `DatasetEpisodeRecord` 读取对应 Parquet/JSONL/manifest。
- 实现总方案 `0.8.9` 的最低门禁：
  - `schema_valid`
  - `time_monotonic`
  - `frame_completeness`
  - `no_nan_inf`
  - `mechanical_limits_respected`
  - `geometry_consistency`
  - `online_offline_separation`
  - `replay_ready`
  - `event_consistency`
  - `dataset_leak_check` 的 episode 内预检部分
- 写出单 episode `quality_report.json`。
- 对 failed episode 生成 quarantine 记录。

不做：

- 不修改原始 Parquet/JSONL。
- 不重新计算物理轨迹。
- 不重新生成离线标签。
- 不决定 train/val/test 归属；split 属于 Task 05。

## 接口与数据结构（签名级别）

```python
QUALITY_CHECKS = (
    "schema_valid",
    "time_monotonic",
    "frame_completeness",
    "no_nan_inf",
    "mechanical_limits_respected",
    "geometry_consistency",
    "online_offline_separation",
    "replay_ready",
    "event_consistency",
)


class DatasetQualityGate:
    def __init__(
        self,
        *,
        min_duration_s: float | None = 300.0,
        required_offline_labels: bool = True,
    ) -> None: ...

    def evaluate_episode(
        self,
        episode: DatasetEpisodeRecord,
    ) -> DatasetQualityReport: ...

    def evaluate_many(
        self,
        episodes: Sequence[DatasetEpisodeRecord],
    ) -> list[DatasetQualityReport]: ...
```

`frame_completeness` 规则：

```text
trajectories 每帧必须有 N 条 crane row。
pair_risks 每帧必须有 N*(N-1)/2 条 unordered pair row。
weather 每帧至少 1 条。
frame index 从最小值开始单调递增，允许末尾因 terminal 结束短于配置 duration。
```

`online_offline_separation` 规则：

```text
logs/llm_observations.jsonl 不得含 offline/future/collision_label/min_clearance_future/ttc_* 真值字段。
visual/frames.jsonl 实时路径导出的帧不得含 offline_labels。
pair_risks.parquet 可以含 offline label 列。
```

## 前置依赖

- Task 01 schema。
- Task 02 catalog 产出的 episode records。
- Module L recorder schema 和文件结构。
- PyArrow。

## 验收标准（具体、可测试）

- 完整 fixture episode 返回 `quality_status="passed"`。
- 缺失 `trajectories.parquet` 返回 failed，并记录 `schema_valid` 或 `missing_file` 失败。
- `time_s` 逆序返回 failed。
- 每帧 trajectory row 数小于 `num_cranes` 返回 failed。
- 核心浮点字段含 NaN/Inf 返回 failed。
- observation 中出现 `min_clearance_future_5s_m` 返回 failed。
- episode 少于 `min_duration_s` 但有 terminal success 原因时可 warning；无原因时 failed 或 warning 取决于 options。
- `quality_report.json` 可被 `DatasetQualityReport.model_validate()`。

## 测试要点（正常 + 边界 + 异常）

正常：

- 双塔吊 3 帧完整 Parquet fixture。
- 单塔吊 episode，pair_risks 允许 0 pair。
- 含 offline label 的 `pair_risks.parquet` 合法。

边界：

- 空 tasks。
- `scenario_id=None`。
- terminal episode duration 小于 300 秒但 summary 记录 shorter reason。
- warning-only episode 可以进入候选集，但 summary 中保留 warning。

异常：

- Parquet 文件损坏。
- JSONL 某一行无法解析。
- manifest frame_count 与 Parquet frame 不一致。
- observation 泄漏 offline/future 字段。
- run_dir 路径不存在。

## 依赖关系

依赖 Task 01 和 Task 02。Task 05、Task 07、Task 08、Task 09 依赖本任务。
