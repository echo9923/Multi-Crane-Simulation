# Task 01：Dataset Schema 与错误模型

## 任务目标

定义 Module O 拥有的数据集构建 schema、summary schema、manifest schema、质量报告 schema、错误码和 warning 对象，为后续 catalog、quality、split、window index、CLI 和 API 查询提供统一合同。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/schemas/dataset.py`。
- 定义 `DATASET_SCHEMA_VERSION = "1.0"`。
- 定义 O 专属错误码和 `DatasetBuildError`。
- 定义 `DatasetBuildWarning`、`DatasetBuildOptions`、`DatasetEpisodeRecord`、`DatasetQualityReport`、`DatasetSplitAssignment`、`DatasetWindowIndexRow`、`DatasetFileRecord`、`DatasetManifest`、`DatasetSummary`、`DatasetBuildResult`。
- 所有 Pydantic schema 使用 `extra="forbid"`、`allow_inf_nan=False`、`validate_default=True`。
- 对 secret-like 字段提供静态拒绝/脱敏检查 helper。

不做：

- 不读取文件。
- 不生成 episode。
- 不做质量门禁计算。
- 不做 split 或 window index。
- 不新增 API route。
- 不修改 Module A 的 `DatasetConfig` 字段结构，除非实现阶段发现现有字段无法表达目标文档要求，并先同步文档。

## 接口与数据结构（签名级别）

建议错误码：

```python
DATASET_E_CONFIG_INVALID = "DATASET_E_CONFIG_INVALID"
DATASET_E_SOURCE_NOT_FOUND = "DATASET_E_SOURCE_NOT_FOUND"
DATASET_E_EPISODE_DISCOVERY_FAILED = "DATASET_E_EPISODE_DISCOVERY_FAILED"
DATASET_E_QUALITY_FAILED = "DATASET_E_QUALITY_FAILED"
DATASET_E_SPLIT_LEAKAGE = "DATASET_E_SPLIT_LEAKAGE"
DATASET_E_INSUFFICIENT_EPISODES = "DATASET_E_INSUFFICIENT_EPISODES"
DATASET_E_WINDOW_INDEX_FAILED = "DATASET_E_WINDOW_INDEX_FAILED"
DATASET_E_WRITE_FAILED = "DATASET_E_WRITE_FAILED"
DATASET_W_RISK_TARGET_MISSED = "DATASET_W_RISK_TARGET_MISSED"
DATASET_W_UNKNOWN_SCENARIO_CLASS = "DATASET_W_UNKNOWN_SCENARIO_CLASS"
DATASET_W_SHORT_EPISODE_INCLUDED = "DATASET_W_SHORT_EPISODE_INCLUDED"
```

建议核心模型：

```python
class DatasetBuildWarning(DatasetBaseModel):
    schema_version: str = DATASET_SCHEMA_VERSION
    warning_code: str
    message: str
    episode_id: str | None = None
    split: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class DatasetBuildOptions(DatasetBaseModel):
    source_roots: list[Path]
    output_root: Path
    max_episodes: int | None = Field(default=None, gt=0)
    min_duration_s: float | None = Field(default=300.0, ge=0)
    copy_mode: Literal["copy", "symlink", "hardlink", "index_only"] = "index_only"
    fail_on_quality_error: bool = False
    include_quarantine_in_summary: bool = True


class DatasetEpisodeRecord(DatasetBaseModel):
    schema_version: str = DATASET_SCHEMA_VERSION
    episode_id: str
    scenario_id: str | None = None
    experiment_id: str | None = None
    run_dir: Path
    episode_status: str
    duration_s: float = Field(ge=0)
    frame_count: int = Field(ge=0)
    num_cranes: int = Field(ge=0)
    scenario_class: str = "unknown"
    layout_hash: str | None = None
    resolved_config_hash: str | None = None
    operator_profile_distribution: dict[str, int] = Field(default_factory=dict)
    risk_frame_ratio_by_level: dict[str, float] = Field(default_factory=dict)
    near_miss_count: int = Field(ge=0)
    collision_count: int = Field(ge=0)
    source_files: dict[str, Path] = Field(default_factory=dict)


class DatasetQualityReport(DatasetBaseModel):
    schema_version: str = DATASET_SCHEMA_VERSION
    episode_id: str
    quality_status: Literal["passed", "warning", "failed"]
    failed_checks: list[str] = Field(default_factory=list)
    warnings: list[DatasetBuildWarning] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class DatasetSplitAssignment(DatasetBaseModel):
    schema_version: str = DATASET_SCHEMA_VERSION
    episode_id: str
    split: Literal[
        "train",
        "val",
        "test",
        "test_seen_layout",
        "test_unseen_layout",
        "test_unseen_num_cranes",
        "test_high_risk",
    ]
    reason: str
    holdout_flags: dict[str, bool] = Field(default_factory=dict)


class DatasetWindowIndexRow(DatasetBaseModel):
    schema_version: str = DATASET_SCHEMA_VERSION
    dataset_id: str
    split: str
    episode_id: str
    scenario_id: str | None = None
    start_frame: int = Field(ge=0)
    input_steps: int = Field(gt=0)
    pred_steps: int = Field(gt=0)
    stride_steps: int = Field(gt=0)
    input_start_time_s: float = Field(ge=0)
    prediction_end_time_s: float = Field(ge=0)
    num_cranes: int = Field(gt=0)
    label_horizons_s: list[float]
    source_paths: dict[str, str]


class DatasetSummary(DatasetBaseModel):
    schema_version: str = DATASET_SCHEMA_VERSION
    dataset_id: str
    created_at: str
    git_commit: str | None = None
    num_episodes: int = Field(ge=0)
    num_quarantined: int = Field(ge=0)
    split_counts: dict[str, int]
    window_counts: dict[str, int]
    risk_distribution: dict[str, float]
    task_completion_rate: float | None = Field(default=None, ge=0, le=1)
    near_miss_count: int = Field(ge=0)
    collision_count: int = Field(ge=0)
    targets: dict[str, Any] = Field(default_factory=dict)
    target_gaps: dict[str, Any] = Field(default_factory=dict)
    warnings: list[DatasetBuildWarning] = Field(default_factory=list)
```

实际实现可以在字段名上小幅调整，但必须保证 M 能读取 `dataset_id`、`num_episodes`、`created_at`，P 能读取 window index，summary 能表达 target/actual/gap/quarantine。

## 前置依赖

- Module A 已有 `DatasetConfig`。
- Module L 已有 `EpisodeSummary`、`EpisodeManifest` 和 recorder row schema。
- Module K 已有离线标签字段与风险等级语义。

## 验收标准（具体、可测试）

- `DatasetSummary.model_validate(valid_payload)` 通过。
- 所有 O schema 拒绝 extra 字段。
- 所有 O schema 拒绝 NaN/Inf。
- `DatasetSplitAssignment` 只允许定义的 split 名称。
- `DatasetWindowIndexRow` 拒绝 `input_steps <= 0`、`pred_steps <= 0`、空 `label_horizons_s`。
- `DatasetBuildError` 可携带 code、message、details，并可被 CLI 转换为非零退出码。
- secret-like key，例如 `api_key`、`authorization`、`secret`，在 manifest/summary payload 静态扫描中被拒绝或脱敏。

## 测试要点（正常 + 边界 + 异常）

正常：

- 构造含 2 个 split、3 个 risk level、1 个 warning 的 summary。
- 构造一个完整 window index row。
- 构造一个 quality passed report。

边界：

- `num_episodes=0` 的空数据集 summary 可表达但构建阶段不一定允许成功。
- `git_commit=None` 可表达，用 warning 标记无法获取 commit。
- `scenario_id=None` 的 episode record 可表达。

异常：

- extra 字段失败。
- NaN/Inf 失败。
- 非法 split 失败。
- secret-like payload 失败。

## 依赖关系

本任务无 Module O 内部前置任务。Task 02-09 都依赖本任务。
