# Module P Overview：STGNN 训练样本转换边界

## 职责

Module P 是仿真系统的训练数据适配层。它读取 Module O 生成的数据集 manifest、split、window index，以及 Module L/K 落盘的 episode 权威 Parquet 文件，把每个窗口转换为可复现、可验证、无时间泄漏的 STGNN / 轨迹预测样本，并提供可直接接入 PyTorch 的 `Dataset` / `DataLoader` 入口。

P 的核心原则是**只转换、校验、索引、统计，不重新划分、不重算真值、不修改权威数据**。训练样本的 split 必须来自 O，轨迹标签必须来自 L 的 `trajectories.parquet`，风险标签必须来自 K 写入的 `pair_risks.parquet`。P 不运行仿真、不生成 episode、不做 dataset split、不计算离线风险标签，也不把前端展示数据写入训练真值。

## 输入

P 消费以下上游文件和配置：

- Module A：`DatasetConfig`，尤其是 `windows.input_steps`、`windows.pred_steps`、`windows.stride_steps`、`windows.risk_label_horizons_s`、采样配置和 `dataset_id`。
- Module O：`metadata/dataset_manifest.json`、`metadata/dataset_summary.json`、`metadata/split_manifest.json` 或等价 split manifest、`index/windows.parquet`。
- Module O：`index/files.parquet` 或 `DatasetWindowIndexRow.source_paths` 中的源文件引用。
- Module L：每个 episode 的 `data/trajectories.parquet`、`data/pair_risks.parquet`、`data/graph_edges.parquet`、`data/tasks.parquet`、`metadata/episode_summary.json`、`visual/episode_manifest.json`。
- Module K：已经写入 `pair_risks.parquet` 的 `risk_level_{horizon}`、`collision_label_{horizon}`、`min_clearance_future_{horizon}`、`ttc_{horizon}` 等离线标签字段。

P 只读取这些文件。任何需要更新、补写、重算或修复上游文件的情况，都应该报 conversion error 并交给对应上游模块处理。

## 输出

第一版建议输出目录：

```text
runs/datasets/{dataset_id}/training/stgnn/
  metadata/
    stgnn_manifest.json
    stgnn_summary.json
    conversion_report.json
  index/
    samples.parquet
  tensors/
    train/
      samples.npz
    val/
      samples.npz
    test/
      samples.npz
    ...
```

实现阶段也可以先只提供内存 Dataset 和 `samples.parquet` 索引，不强制写全量 tensor 文件；但 manifest、summary、metadata 和样本 API 必须能完整追溯到 O 的 window row 与 L/K 的源文件。

## 样本结构

单个样本建议使用以下逻辑结构：

```python
class StgnnSample:
    X_node: np.ndarray
    X_edge: np.ndarray
    A_phy: np.ndarray
    Y_traj: np.ndarray
    Y_risk: np.ndarray
    node_mask: np.ndarray
    edge_mask: np.ndarray
    risk_mask: np.ndarray
    metadata: StgnnSampleMetadata
```

建议维度约定：

```text
X_node:   [input_steps, max_nodes, node_feature_dim]
X_edge:   [input_steps, max_nodes, max_nodes, edge_feature_dim]
A_phy:    [input_steps, max_nodes, max_nodes]
Y_traj:   [pred_steps, max_nodes, traj_target_dim]
Y_risk:   [risk_horizons, max_nodes, max_nodes, risk_target_dim]
node_mask:[max_nodes]
edge_mask:[max_nodes, max_nodes]
risk_mask:[risk_horizons, max_nodes, max_nodes]
```

`max_nodes` 由可变塔吊策略决定。第一版采用 split/batch 内 padding + mask 策略，不因为 episode 的 `num_cranes` 不同而重新划分 split。模型或 collate 层可以用 `node_mask` 和 `edge_mask` 忽略 padding 位置。

## Feature 策略

`X_node` 来自输入窗口内的 `trajectories.parquet`，第一版覆盖物理状态、几何位置、速度、载荷、任务上下文、天气镜像和基础 operator 字段：

- 运动与几何：`theta_sin`、`theta_cos`、`theta_dot_rad_s`、`trolley_r_m`、`trolley_v_m_s`、`hook_h_m`、`hoist_v_m_s`。
- 空间位置：`root_x/y/z`、`tip_x/y/z`、`hook_x/y/z`。
- 载荷与任务：`load_attached`、`load_weight_t`、`task_stage`、`task_id` presence、zone id presence 或稳定编码。
- 环境：`wind_speed_m_s`、`wind_gust_m_s`、`wind_direction_deg`、`visibility_level` 稳定编码。

`X_edge` 和 `A_phy` 来自输入窗口内的 `graph_edges.parquet` 与 `pair_risks.parquet` 当前时刻字段。第一版允许在 `graph_edges.parquet` 缺少可选 edge 字段时用 `pair_risks.parquet` 的当前距离和风险等级补齐边特征，但不得用预测窗口后的任何字段作为输入 feature。

禁止作为输入 feature：

- `min_clearance_future_*`、`ttc_*`、`risk_level_*`、`collision_label_*` 等离线未来标签。
- 预测窗口内或预测窗口之后的 trajectory、risk、task、weather 行。
- 前端 `visual/frames.jsonl` 中 display-only 的距离、风险或派生值。
- provider secret、raw API key、Authorization header、token、password 等敏感信息。

## Label 策略

`Y_traj` 来自同一 episode 的 `trajectories.parquet` 中预测窗口 `[start_frame + input_steps, start_frame + input_steps + pred_steps)`。第一版轨迹标签覆盖每台塔吊未来 `theta_sin`、`theta_cos`、`trolley_r_m`、`hook_h_m`、`hook_x/y/z`，具体 target 维度在 schema 任务中固定。

`Y_risk` 来自输入结束帧或窗口规定 anchor frame 的 `pair_risks.parquet` 离线标签列。第一版使用 `DatasetConfig.windows.risk_label_horizons_s` 对应的 `risk_level_{horizon}` 和 `collision_label_{horizon}`，并可附加 `min_clearance_future_{horizon}` 和 `ttc_{horizon}` 作为监督目标。P 不重算风险标签，不把在线 `risk_level_now` 当作未来风险真值。

## 无泄漏原则

P 必须同时避免 split 泄漏和时间泄漏：

- 不重新随机划分 train/val/test。
- 不按滑动窗口重新打散导致同一 episode、scenario、layout 或 `num_cranes` 跨 split。
- 每个样本只能来自一个 episode 内的连续窗口。
- 输入窗口只读取 `[start_frame, start_frame + input_steps)`。
- 轨迹标签只读取预测窗口。
- 风险标签只读取 K 已经写入的离线 label 字段，不读取预测窗口之后的轨迹来临时计算 label。
- sample metadata 必须记录 O window row 的 `dataset_id`、`split`、`scenario_id`、`episode_id`、`start_frame`、窗口参数和源文件引用。

## 对外接口

建议新增 schema：

```python
TRAINING_SCHEMA_VERSION = "1.0"

class TrainingConversionError(RuntimeError): ...
class StgnnFeatureSpec(BaseModel): ...
class StgnnConversionOptions(BaseModel): ...
class StgnnSampleMetadata(BaseModel): ...
class StgnnSampleIndexRow(BaseModel): ...
class StgnnTensorSample(BaseModel): ...
class StgnnConversionSummary(BaseModel): ...
class StgnnManifest(BaseModel): ...
```

建议新增核心服务：

```python
class DatasetWindowReader:
    def read(self, dataset_root: Path) -> list[DatasetWindowIndexRow]: ...

class EpisodeParquetSource:
    def load(self, window: DatasetWindowIndexRow) -> EpisodeTables: ...

class StgnnSampleBuilder:
    def build_sample(self, window: DatasetWindowIndexRow) -> StgnnTensorSample: ...

class StgnnDatasetConverter:
    def convert(self, dataset_root: Path, output_root: Path) -> StgnnConversionResult: ...
```

PyTorch 适配层独立于核心转换逻辑：

```python
class StgnnTorchDataset(torch.utils.data.Dataset):
    def __init__(self, samples: Sequence[StgnnTensorSample] | Path, *, split: str | None = None) -> None: ...
    def __len__(self) -> int: ...
    def __getitem__(self, index: int) -> dict[str, torch.Tensor | dict]: ...

def stgnn_collate_fn(batch: Sequence[dict]) -> dict[str, torch.Tensor | list[dict]]: ...
```

## 对内依赖边界

允许：

- 读取 A 的 `DatasetConfig` 与 O 的 dataset/window schema。
- 读取 L/K 产出的权威 Parquet 和 JSON manifest。
- 使用 PyArrow、NumPy 和 Pydantic 构造训练样本。
- 在 PyTorch 适配层中导入 `torch`。
- 生成训练样本索引、tensor cache、转换 summary 和诊断报告。
- 对 schema、字段、时间轴、split、secret 和泄漏做严格校验。

不允许：

- 调用仿真主循环、runner、scheduler 或 batch generation。
- 修改 O 的 manifest、summary、split、windows 或任何 L episode 权威文件。
- 重新计算 Module K 离线风险标签。
- 重新划分 dataset split。
- 把 front-end display-only 数据写入训练真值。
- 把完整 secret 写入样本、metadata、summary、日志或错误 payload。
- 在核心转换层强依赖 PyTorch。

## 失败边界

| 失败 | 默认处理 |
| --- | --- |
| dataset manifest 缺失或 schema version 不兼容 | conversion failed，`TRAINING_E_MANIFEST_INVALID` |
| windows.parquet 缺失、字段不完整或无法校验 | conversion failed，`TRAINING_E_WINDOWS_INVALID` |
| window row 的 split 与 split manifest 不一致 | conversion failed，`TRAINING_E_SPLIT_LEAKAGE` |
| episode 源文件缺失或不可读 | conversion failed 或跳过样本并 summary 记录，取决于 options |
| trajectory 时间轴缺帧、重复帧或 crane 集合不一致 | conversion failed，`TRAINING_E_TIME_AXIS_INVALID` |
| 输入 feature 读取到 future label 字段 | conversion failed，`TRAINING_E_TIME_LEAKAGE` |
| label 字段缺失 | conversion failed，`TRAINING_E_LABEL_MISSING` |
| 可变塔吊数量无法 padding 或超出 max_nodes 策略 | conversion failed，`TRAINING_E_VARIABLE_NODES_UNSUPPORTED` |
| metadata/summary/error payload 中发现 secret-like key 或 raw secret | conversion failed，`TRAINING_E_SECRET_LEAKAGE` |
| PyTorch 未安装但用户只调用核心转换 | 不失败 |
| PyTorch 未安装但用户调用 torch Dataset | import-time 或 construction-time 明确报错 |

## 权威来源

若本文档与根目录 `目标.md` 或上游文档冲突，以 `目标.md` 中 Module P 的硬性阶段闸口、Module O 的 split/window 输出、Module L 的 Parquet 权威表、Module K 的离线标签合同和当前已实现 schema 为准，并同步修订本文档。
