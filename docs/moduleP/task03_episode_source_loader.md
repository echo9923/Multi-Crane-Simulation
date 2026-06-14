# Task 03：Episode 源 Parquet 读取、字段校验与时间轴对齐

## 任务目标

根据 O 的 window row 和 source file 引用读取单个 episode 的权威 Parquet/JSON 文件，校验轨迹、风险、边、任务表字段完整性和时间轴一致性，为后续样本构造提供只读 `EpisodeTables`。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/training/episode_source.py`。
- 解析 window row 中的 `source_paths`，定位 `trajectories`、`pair_risks`、`graph_edges`、`tasks`、`episode_summary`、`episode_manifest`。
- 使用 PyArrow 读取 Parquet，保留 table 或转为按 frame 索引的轻量结构。
- 校验必需字段、schema version、episode_id、frame/time 单调性、crane_id 集合。
- 校验窗口所需输入帧和预测帧都在 trajectory 表中。
- 校验风险标签 anchor frame 所需 pair rows 和 horizon 字段存在。
- 校验 graph_edges 缺失时只触发允许的 fallback 路径，不静默吞掉必需字段。

不做：

- 不构造 `X_node`、`X_edge`、`A_phy`、`Y_traj`、`Y_risk`。
- 不重算 graph edge 或 pair risk。
- 不修改源文件。
- 不读取 `visual/frames.jsonl` 作为训练权威。

## 接口与数据结构（签名级别）

```python
class EpisodeTables:
    episode_id: str
    scenario_id: str | None
    trajectories: pyarrow.Table
    pair_risks: pyarrow.Table
    graph_edges: pyarrow.Table | None
    tasks: pyarrow.Table | None
    episode_summary: dict[str, Any]
    episode_manifest: dict[str, Any]
    source_paths: dict[str, Path]


class EpisodeParquetSource:
    def __init__(self, *, dataset_root: Path) -> None: ...

    def load_for_window(self, window: DatasetWindowIndexRow) -> EpisodeTables: ...

    def validate_for_window(
        self,
        *,
        window: DatasetWindowIndexRow,
        tables: EpisodeTables,
    ) -> None: ...
```

必需 trajectory 字段：

```text
schema_version, episode_id, frame, time_s, crane_id,
theta_sin, theta_cos, theta_dot_rad_s,
trolley_r_m, trolley_v_m_s, hook_h_m, hoist_v_m_s,
root_x, root_y, root_z, tip_x, tip_y, tip_z, hook_x, hook_y, hook_z,
load_attached, task_stage
```

必需 pair_risks 字段：

```text
schema_version, episode_id, frame, time_s, crane_i, crane_j,
clearance_min_now_m, risk_level_now
```

并按 `risk_label_horizons_s` 要求存在：

```text
risk_level_{horizon}, collision_label_{horizon},
min_clearance_future_{horizon}_m, ttc_{horizon}_s
```

其中 horizon 规范化为 `5s`、`10s`、`15s` 形式并映射到现有 Parquet 列名，例如 `risk_level_5s`。

## 前置依赖

- Task 01 training schema。
- Task 02 window reader。
- Module L recorder row schema。
- Module K risk label 字段语义。

## 验收标准（具体、可测试）

- 对合法 tiny episode，`load_for_window()` 返回包含 trajectories、pair_risks 和 source_paths 的 `EpisodeTables`。
- trajectory 对每个输入/预测 frame 都包含相同 crane_id 集合。
- trajectory frame/time 单调递增；重复 frame/crane 行被拒绝。
- window 所需最大 exclusive frame 超过 trajectory 最大 frame 时抛 `TRAINING_E_TIME_AXIS_INVALID`。
- pair_risks 缺少指定 horizon label 列时抛 `TRAINING_E_LABEL_MISSING`。
- graph_edges 缺失时只有 `allow_graph_edge_fallback=True` 的 options 允许继续，并记录 warning。
- episode_id 与 window.episode_id 不一致时抛 `TRAINING_E_SOURCE_SCHEMA_INVALID`。
- 源文件路径或错误 details 不包含 raw secret。

## 测试要点（正常 + 边界 + 异常）

正常：

- 3 台塔吊、`input_steps=2`、`pred_steps=2` 的 tiny Parquet。
- pair_risks 包含 `5s`、`10s`、`15s` label。
- graph_edges 存在且字段完整。

边界：

- 单塔吊 episode 没有 pair rows，允许 trajectory 样本，但 risk label 输出为空 mask。
- `tasks.parquet` 缺失时节点任务上下文使用 trajectory 中已有 task 字段。
- 可选 numeric 字段为 null 时按 feature 默认值策略处理，不改源表。

异常：

- trajectories 缺 `hook_x`。
- pair_risks 缺 `collision_label_10s`。
- frame 0 有 3 台塔吊，frame 1 只有 2 台塔吊。
- `time_s` 非单调。
- `episode_id` 混入另一 episode。

## 依赖关系

依赖 Task 01、Task 02。Task 04、Task 05、Task 06、Task 07、Task 08、Task 10 依赖本任务。
