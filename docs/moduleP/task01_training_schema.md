# Task 01：Training Schema 与 Conversion Error

## 任务目标

定义 Module P 的训练样本 schema、feature spec、manifest/summary schema、错误码和 secret 清洗合同，为后续读取、转换、统计、PyTorch 适配和 CLI 提供统一接口。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/schemas/training.py`。
- 定义 `TRAINING_SCHEMA_VERSION = "1.0"`。
- 定义 Module P 专属错误码和 `TrainingConversionError`。
- 定义 `StgnnFeatureSpec`、`StgnnConversionOptions`、`StgnnSampleMetadata`、`StgnnSampleIndexRow`、`StgnnTensorSample`、`StgnnManifest`、`StgnnConversionSummary`、`StgnnConversionResult`。
- 所有新增 Pydantic schema 使用 `extra="forbid"`、`allow_inf_nan=False`、`validate_default=True`。
- 定义 secret-like key/value 静态拒绝和脱敏 helper 的签名。
- 固定第一版 feature/label 名称、tensor 维度语义和可变塔吊策略字段。

不做：

- 不读取 dataset 或 Parquet 文件。
- 不生成 tensor。
- 不导入 PyTorch。
- 不实现 CLI。
- 不修改 Module O/L/K 的权威 schema。

## 接口与数据结构（签名级别）

建议错误码：

```python
TRAINING_E_CONFIG_INVALID = "TRAINING_E_CONFIG_INVALID"
TRAINING_E_MANIFEST_INVALID = "TRAINING_E_MANIFEST_INVALID"
TRAINING_E_WINDOWS_INVALID = "TRAINING_E_WINDOWS_INVALID"
TRAINING_E_SPLIT_LEAKAGE = "TRAINING_E_SPLIT_LEAKAGE"
TRAINING_E_SOURCE_MISSING = "TRAINING_E_SOURCE_MISSING"
TRAINING_E_SOURCE_SCHEMA_INVALID = "TRAINING_E_SOURCE_SCHEMA_INVALID"
TRAINING_E_TIME_AXIS_INVALID = "TRAINING_E_TIME_AXIS_INVALID"
TRAINING_E_TIME_LEAKAGE = "TRAINING_E_TIME_LEAKAGE"
TRAINING_E_LABEL_MISSING = "TRAINING_E_LABEL_MISSING"
TRAINING_E_VARIABLE_NODES_UNSUPPORTED = "TRAINING_E_VARIABLE_NODES_UNSUPPORTED"
TRAINING_E_SECRET_LEAKAGE = "TRAINING_E_SECRET_LEAKAGE"
TRAINING_E_WRITE_FAILED = "TRAINING_E_WRITE_FAILED"
```

建议 feature spec：

```python
class StgnnFeatureSpec(TrainingBaseModel):
    schema_version: str = TRAINING_SCHEMA_VERSION
    node_features: list[str]
    edge_features: list[str]
    traj_targets: list[str]
    risk_targets: list[str]
    risk_label_horizons_s: list[float]
    variable_node_strategy: Literal["pad_and_mask"] = "pad_and_mask"
    max_nodes: int = Field(gt=0)
```

第一版默认字段：

```text
node_features =
  theta_sin, theta_cos, theta_dot_rad_s,
  trolley_r_m, trolley_v_m_s, hook_h_m, hoist_v_m_s,
  root_x, root_y, root_z, tip_x, tip_y, tip_z, hook_x, hook_y, hook_z,
  load_attached, load_weight_t, task_stage_code, has_task,
  wind_speed_m_s, wind_gust_m_s, wind_direction_sin, wind_direction_cos,
  visibility_code

edge_features =
  edge_distance_m, edge_overlap_ratio, edge_delta_height_m,
  edge_delta_theta_rad, edge_delta_theta_dot_rad_s,
  clearance_min_now_m, risk_level_now_code

traj_targets =
  theta_sin, theta_cos, trolley_r_m, hook_h_m, hook_x, hook_y, hook_z

risk_targets =
  risk_level_code, collision_label, min_clearance_future_m, ttc_s
```

建议 metadata：

```python
class StgnnSampleMetadata(TrainingBaseModel):
    schema_version: str = TRAINING_SCHEMA_VERSION
    dataset_id: str
    split: str
    scenario_id: str | None = None
    episode_id: str
    start_frame: int = Field(ge=0)
    input_steps: int = Field(gt=0)
    pred_steps: int = Field(gt=0)
    stride_steps: int = Field(gt=0)
    risk_label_horizons_s: list[float]
    source_paths: dict[str, str]
    source_window_index: dict[str, Any]
    feature_spec_hash: str
```

建议 tensor sample：

```python
class StgnnTensorSample(TrainingBaseModel):
    metadata: StgnnSampleMetadata
    X_node: np.ndarray
    X_edge: np.ndarray
    A_phy: np.ndarray
    Y_traj: np.ndarray
    Y_risk: np.ndarray
    node_mask: np.ndarray
    edge_mask: np.ndarray
    risk_mask: np.ndarray
```

如果 Pydantic 对 `np.ndarray` 校验过重，实现阶段可将 schema 分为 metadata/index 的 Pydantic 对象和运行时 dataclass；但文档合同中的字段名和维度必须保持一致。

建议 index/summary：

```python
class StgnnSampleIndexRow(TrainingBaseModel):
    schema_version: str = TRAINING_SCHEMA_VERSION
    sample_id: str
    dataset_id: str
    split: str
    episode_id: str
    scenario_id: str | None = None
    start_frame: int = Field(ge=0)
    tensor_path: str | None = None
    tensor_offset: int | None = Field(default=None, ge=0)
    num_nodes: int = Field(gt=0)
    max_nodes: int = Field(gt=0)
    input_steps: int = Field(gt=0)
    pred_steps: int = Field(gt=0)
    node_feature_dim: int = Field(gt=0)
    edge_feature_dim: int = Field(gt=0)
    traj_target_dim: int = Field(gt=0)
    risk_target_dim: int = Field(gt=0)
    metadata_json: dict[str, Any]

class StgnnConversionSummary(TrainingBaseModel):
    schema_version: str = TRAINING_SCHEMA_VERSION
    dataset_id: str
    sample_counts: dict[str, int]
    skipped_counts: dict[str, int] = Field(default_factory=dict)
    num_episodes: int = Field(ge=0)
    max_nodes: int = Field(gt=0)
    feature_spec: StgnnFeatureSpec
    risk_distribution: dict[str, float] = Field(default_factory=dict)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
```

## 前置依赖

- Module A 已有 `DatasetConfig`。
- Module O 已有 `DatasetWindowIndexRow`、`DatasetManifest`、`DatasetSummary`。
- Module L 已有 recorder Parquet row schema。
- Module K 已有离线风险标签字段语义。

## 验收标准（具体、可测试）

- `StgnnFeatureSpec` 可构造默认 spec，并拒绝空 feature 列表。
- `StgnnSampleMetadata` 必须包含 `dataset_id`、`split`、`episode_id`、`start_frame`、窗口参数和 `source_paths`。
- `risk_label_horizons_s` 拒绝空列表、非正数和重复值。
- `max_nodes <= 0` 校验失败。
- `StgnnSampleIndexRow` 拒绝 `num_nodes > max_nodes`。
- schema 拒绝 extra 字段、NaN 和 Inf。
- `TrainingConversionError` 可携带 code、message、details，并且 `str(error)` 不包含 raw secret。
- secret-like key，例如 `api_key`、`authorization`、`secret`、`token`、`password`，在 metadata/summary/error payload 静态扫描中被拒绝或脱敏。

## 测试要点（正常 + 边界 + 异常）

正常：

- 构造含 train/val/test sample counts 的 `StgnnConversionSummary`。
- 构造一个完整 `StgnnSampleMetadata` 和 `StgnnSampleIndexRow`。
- 构造默认 feature spec 并计算稳定 hash。

边界：

- `scenario_id=None` 合法。
- `tensor_path=None` 合法，表示仅内存样本。
- `skipped_counts={}` 合法。

异常：

- extra 字段失败。
- NaN/Inf 失败。
- secret-like metadata 失败。
- `risk_label_horizons_s=[]` 或 `[0]` 失败。
- `num_nodes > max_nodes` 失败。

## 依赖关系

本任务无 Module P 内部前置任务。Task 02-12 都依赖本任务。
