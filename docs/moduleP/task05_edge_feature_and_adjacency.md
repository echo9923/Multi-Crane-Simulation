# Task 05：边特征 X_edge 与物理先验邻接 A_phy 构造

## 任务目标

从输入窗口内的 `graph_edges.parquet` 和当前时刻 `pair_risks.parquet` 构造 STGNN 边特征 `X_edge` 与物理先验邻接矩阵 `A_phy`，禁止使用任何未来标签字段作为输入。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/training/edge_features.py`。
- 读取输入窗口内 graph edge rows，映射到 `[T_in, max_nodes, max_nodes, F_edge]`。
- 构造 `A_phy [T_in, max_nodes, max_nodes]`，对真实有向边或物理相关边赋权。
- 用 `pair_risks` 当前字段补充 `clearance_min_now_m`、`risk_level_now` 等 edge feature。
- 生成 `edge_mask [max_nodes, max_nodes]`。
- 对 graph_edges 缺失的允许 fallback 策略进行显式 warning。

不做：

- 不使用 `risk_level_5s`、`collision_label_10s`、`min_clearance_future_*`、`ttc_*` 等未来标签作为输入。
- 不计算新的几何距离。
- 不构造风险 label。
- 不修改 graph_edges 或 pair_risks。

## 接口与数据结构（签名级别）

```python
class EdgeFeatureBuilder:
    def __init__(self, *, feature_spec: StgnnFeatureSpec) -> None: ...

    def build(
        self,
        *,
        window: DatasetWindowIndexRow,
        tables: EpisodeTables,
        crane_order: Sequence[str],
        max_nodes: int,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return X_edge [T_in, N, N, F_edge], A_phy [T_in, N, N], edge_mask [N, N]."""
```

边映射规则：

```text
graph_edges uses src_crane_id -> dst_crane_id.
pair_risks uses unordered crane_i/crane_j.
For pair_risks current fields, mirror values to both directions i->j and j->i.
No self edge feature by default; A_phy diagonal is 0 unless feature_spec later opts in.
Padding rows/cols are zero and edge_mask is false.
```

`A_phy` 第一版权重规则：

```text
if graph_edges.edge_weight_physics_prior exists:
  use clipped finite value in [0, 1]
else if edge_distance_m exists:
  A = 1 / (1 + max(edge_distance_m, 0))
else if clearance_min_now_m exists:
  A = 1 / (1 + max(clearance_min_now_m, 0))
else:
  A = 0 for missing edge
```

## 前置依赖

- Task 01 feature spec。
- Task 03 episode source loader。
- Task 08 variable crane strategy。

## 验收标准（具体、可测试）

- 对 3 台塔吊、2 个 input frame，输出 `X_edge` shape 为 `[2, max_nodes, max_nodes, edge_feature_dim]`。
- `A_phy` shape 为 `[2, max_nodes, max_nodes]`，padding 区域为 0。
- `edge_mask` 对真实非自环 pair 为 `True`，padding 和自环为 `False`。
- pair_risks 当前字段可镜像到两个方向。
- graph_edges 的有向字段保留方向。
- 输出不包含 NaN/Inf。
- 禁止字段出现在 edge feature spec 或输入访问路径时抛 `TRAINING_E_TIME_LEAKAGE`。
- graph_edges 缺失且 fallback 关闭时抛 `TRAINING_E_SOURCE_MISSING`。

## 测试要点（正常 + 边界 + 异常）

正常：

- graph_edges 有向边 + pair_risks 当前 clearance 共同构造 edge feature。
- `edge_weight_physics_prior=0.7` 被写入 A_phy。
- 无 graph edge 权重时使用 distance fallback。

边界：

- 单塔吊 episode 输出全零 edge tensor 和全 false edge mask。
- `edge_overlap_ratio=None` 使用 0.0 和 warning。
- graph_edges 缺失但 fallback 打开，用 pair_risks 当前字段构造有限 edge feature。

异常：

- feature spec 包含 `risk_level_5s`。
- graph_edges frame 超出输入窗口被忽略，若缺输入窗口 frame 则报错。
- `edge_weight_physics_prior=Inf` 被拒绝。

## 依赖关系

依赖 Task 01、Task 03、Task 08。Task 10 依赖本任务。
