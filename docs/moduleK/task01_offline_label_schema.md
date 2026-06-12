# Task 01：Offline Label Schema

## 任务目标

定义 Module K 的离线标签 schema、聚合报告 schema 和错误码，使 `OfflineRiskLabel` 成为训练标签唯一事实源，并与总方案 K.2 输出字段对齐。

## 范围：做什么 / 不做什么

做：

- 修改 `backend/app/schemas/risk.py`。
- 新增 `OFFLINE_LABEL_SCHEMA_VERSION = "1.0"`。
- 新增 `OfflineFutureWindowLabel`，表达任意未来窗口的 min clearance、TTC、risk level 和 collision label。
- 新增 `OfflinePairGeometryDistance`，表达单帧单对塔吊的四类 raw distance 与 clearance。
- 新增 `OfflineRiskLabel`，表达每个 episode、frame、crane pair 的完整标签。
- 新增 `OfflinePairRiskRecord`，表达单个 crane pair 的时序标签集合。
- 新增 `OfflineRiskAggregate` 和 `OfflineRiskReport`，表达正负样本比例、risk level 分布、按 episode/scenario/crane_pair 聚合统计和 warning。
- 新增 `OfflineLabelError` 和 `OFFLINE_LABEL_*` / `OFFLINE_LABEL_W_*` 错误码。
- 扩展 `RiskConfig`，新增 `future_windows_s: list[float] = [5.0, 10.0, 15.0]`，满足未来窗口可配置要求。
- 所有新增 Pydantic schema 使用 `extra="forbid"`、`allow_inf_nan=False`。

不做：

- 不实现几何距离计算。
- 不实现未来窗口扫描、TTC 或 risk level 映射。
- 不实现标签生成器。
- 不读取或写入 Parquet。
- 不修改 `RiskPairResult` 的在线 future truth 禁用规则。
- 不把离线标签字段加入 `Observation`、`WorldSnapshot` 或 prompt 相关 schema。

## 接口与数据结构（签名级别）

建议 schema：

```python
OFFLINE_LABEL_SCHEMA_VERSION = "1.0"

OFFLINE_LABEL_E_EMPTY_TRAJECTORY = "OFFLINE_LABEL_E_EMPTY_TRAJECTORY"
OFFLINE_LABEL_E_MISSING_FRAME = "OFFLINE_LABEL_E_MISSING_FRAME"
OFFLINE_LABEL_E_CRANE_ID_MISMATCH = "OFFLINE_LABEL_E_CRANE_ID_MISMATCH"
OFFLINE_LABEL_E_DUPLICATE_TRAJECTORY_ROW = "OFFLINE_LABEL_E_DUPLICATE_TRAJECTORY_ROW"
OFFLINE_LABEL_E_INVALID_WINDOW = "OFFLINE_LABEL_E_INVALID_WINDOW"
OFFLINE_LABEL_E_INVALID_GEOMETRY = "OFFLINE_LABEL_E_INVALID_GEOMETRY"
OFFLINE_LABEL_W_LOW_POSITIVE_RATIO = "OFFLINE_LABEL_W_LOW_POSITIVE_RATIO"
```

```python
class OfflineFutureWindowLabel(RiskBaseModel):
    schema_version: str = OFFLINE_LABEL_SCHEMA_VERSION
    window_s: float = Field(gt=0)
    min_clearance_future_m: float
    ttc_s: float | None = Field(default=None, ge=0)
    risk_level: RiskLevel
    collision_label: int = Field(ge=0, le=1)
    used_future_truth: Literal[True] = True
```

```python
class OfflinePairGeometryDistance(RiskBaseModel):
    schema_version: str = OFFLINE_LABEL_SCHEMA_VERSION
    distance_min_raw_now_m: float = Field(ge=0)
    clearance_min_now_m: float
    distance_jib_jib_raw_now_m: float = Field(ge=0)
    clearance_jib_jib_now_m: float
    distance_jib_i_hook_j_raw_now_m: float = Field(ge=0)
    clearance_jib_i_hook_j_now_m: float
    distance_jib_j_hook_i_raw_now_m: float = Field(ge=0)
    clearance_jib_j_hook_i_now_m: float
    distance_hook_hook_raw_now_m: float = Field(ge=0)
    clearance_hook_hook_now_m: float
    nearest_object_i: RiskObjectType
    nearest_object_j: RiskObjectType
```

`OfflineRiskLabel` 必须包含 K.2 的显式字段：

```python
class OfflineRiskLabel(RiskBaseModel):
    schema_version: str = OFFLINE_LABEL_SCHEMA_VERSION
    episode_id: str
    scenario_id: str | None = None
    frame: int = Field(ge=0)
    time_s: float = Field(ge=0)
    crane_i: str
    crane_j: str
    pair_id: str

    distance_min_raw_now_m: float = Field(ge=0)
    clearance_min_now_m: float
    distance_jib_jib_raw_now_m: float = Field(ge=0)
    clearance_jib_jib_now_m: float
    distance_jib_i_hook_j_raw_now_m: float = Field(ge=0)
    clearance_jib_i_hook_j_now_m: float
    distance_jib_j_hook_i_raw_now_m: float = Field(ge=0)
    clearance_jib_j_hook_i_now_m: float
    distance_hook_hook_raw_now_m: float = Field(ge=0)
    clearance_hook_hook_now_m: float

    min_clearance_future_5s_m: float
    min_clearance_future_10s_m: float
    ttc_5s_s: float | None = Field(default=None, ge=0)
    ttc_10s_s: float | None = Field(default=None, ge=0)
    risk_level_5s: RiskLevel
    risk_level_10s: RiskLevel
    collision_label_5s: int = Field(ge=0, le=1)
    collision_label_10s: int = Field(ge=0, le=1)

    future_window_labels: dict[str, OfflineFutureWindowLabel] = Field(default_factory=dict)
    used_future_truth: Literal[True] = True
```

校验规则：

- `crane_i < crane_j` 或等价稳定排序，`pair_id == f"{crane_i}-{crane_j}"`。
- `future_window_labels` key 必须是 `{window:g}s` 规范格式，例如 `5s`、`10s`、`15s`。
- 显式 `*_5s`、`*_10s` 字段必须与 `future_window_labels["5s"]`、`future_window_labels["10s"]` 一致。
- `used_future_truth` 必须为 `True`；传入 `False` 应校验失败。
- `collision_label_*` 只能为 `0` 或 `1`。

```python
class OfflinePairRiskRecord(RiskBaseModel):
    schema_version: str = OFFLINE_LABEL_SCHEMA_VERSION
    episode_id: str
    scenario_id: str | None = None
    crane_i: str
    crane_j: str
    pair_id: str
    labels: list[OfflineRiskLabel]
```

```python
class OfflineRiskAggregate(RiskBaseModel):
    schema_version: str = OFFLINE_LABEL_SCHEMA_VERSION
    group_by: Literal["global", "episode", "scenario", "crane_pair"]
    group_key: str
    sample_count: int = Field(ge=0)
    positive_count_5s: int = Field(ge=0)
    positive_ratio_5s: float = Field(ge=0, le=1)
    positive_count_10s: int = Field(ge=0)
    positive_ratio_10s: float = Field(ge=0, le=1)
    risk_level_counts_5s: dict[RiskLevel, int] = Field(default_factory=dict)
    risk_level_counts_10s: dict[RiskLevel, int] = Field(default_factory=dict)
```

```python
class OfflineRiskReport(RiskBaseModel):
    schema_version: str = OFFLINE_LABEL_SCHEMA_VERSION
    total_labels: int = Field(ge=0)
    aggregates: list[OfflineRiskAggregate] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
```

错误对象：

```python
class OfflineLabelError(ValueError):
    error_code: str
    category: Literal["dataset_build_error", "dataset_build_warning"]
    episode_id: str | None
    frame: int | None
    pair_id: str | None
    details: dict[str, Any]
```

配置扩展：

```python
class RiskConfig(ConfigBaseModel):
    geometry_envelope: GeometryEnvelopeConfig
    thresholds_m: RiskThresholdsConfig
    ttc_threshold_level: PriorityLevel
    wind_safe_distance_factor: WindSafeDistanceFactorConfig
    future_windows_s: list[float] = Field(default_factory=lambda: [5.0, 10.0, 15.0])
```

`future_windows_s` 校验：

- 非空。
- 每个窗口 `> 0`。
- 去重后升序保存。
- 必须包含 `5.0` 和 `10.0`，因为 K.2 要求固定列。

## 前置依赖

- `backend/app/schemas/risk.py` 中已有 `RiskBaseModel`、`RiskLevel`、`RiskObjectType`、`RISK_SCHEMA_VERSION` 和 `RISK_E_FUTURE_TRUTH_FORBIDDEN`。
- `backend/app/schemas/config.py` 中已有 `RiskConfig`、`GeometryEnvelopeConfig`、`RiskThresholdsConfig`。
- Pydantic v2。
- `backend/app/schemas/scheduler.py` 中 `FORBIDDEN_OBSERVATION_FIELDS` 已包含离线标签和 future 字段，本任务不修改 observation 允许列表。

## 验收标准（具体、可测试）

- `OfflineRiskLabel` 可用最小完整 payload 构造，并可 `model_dump(mode="json")`。
- `OfflineRiskLabel` 拒绝额外字段。
- `OfflineRiskLabel` 拒绝 NaN/Inf。
- `OfflineRiskLabel.used_future_truth=False` 校验失败。
- `OfflineRiskLabel.collision_label_5s`、`collision_label_10s` 只能是 `0/1`。
- `OfflineRiskLabel.pair_id` 与排序后的 `crane_i`、`crane_j` 一致。
- `future_window_labels["5s"]` 和 `["10s"]` 必须存在，且与显式字段一致。
- `OfflinePairRiskRecord.labels` 只能包含同一 episode、同一 pair 的标签。
- `OfflineRiskReport` 可以表达 global、episode、scenario、crane_pair 四种聚合。
- `RiskConfig.future_windows_s` 默认值为 `[5.0, 10.0, 15.0]`。
- `RiskConfig.future_windows_s=[10.0, 5.0, 5.0, 15.0]` 归一化为 `[5.0, 10.0, 15.0]`。
- `RiskConfig.future_windows_s` 缺少 `5.0` 或 `10.0` 时校验失败。
- `RiskPairResult` 仍拒绝 `used_future_truth=True`，确保在线风险合同未被破坏。

## 测试要点（正常 + 边界 + 异常）

- 正常：构造包含 `5s/10s/15s` 三个窗口的 `OfflineRiskLabel`。
- 正常：构造 `OfflinePairRiskRecord`，labels 按 frame 递增。
- 正常：构造 `OfflineRiskReport`，包含 global 和 crane_pair 聚合。
- 边界：`ttc_*_s=None` 合法；`clearance_min_now_m` 可为负；raw distance 必须非负。
- 边界：`scenario_id=None` 合法。
- 异常：`extra="forbid"` 拒绝 `offline_prompt_hint` 等额外字段。
- 异常：`future_window_labels` key 为 `"5"`、`"5.0sec"` 或负窗口时失败。
- 异常：显式 5s 字段与 map 内 5s 值不一致时失败。
- 异常：`RiskConfig.future_windows_s=[]`、`[0]`、`[15]` 失败。
- 防泄漏：静态断言 `OfflineRiskLabel` 没有被 `Observation`、`WorldSnapshot`、prompt builder、operator orchestrator 导入。

## 依赖关系

本任务是 Module K 的根任务。Task 02-06 都依赖本任务定义的 schema、错误码和 `RiskConfig.future_windows_s`。
