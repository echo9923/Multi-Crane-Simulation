# Task 04：节点特征 X_node 构造

## 任务目标

从输入窗口内的 `trajectories.parquet` 行构造固定维度节点特征 `X_node` 和 `node_mask`，保证只读取输入窗口信息，稳定处理缺失可选字段和离散字段编码。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/training/node_features.py`。
- 基于 `StgnnFeatureSpec.node_features` 构造 `X_node`。
- 只读取 `[start_frame, start_frame + input_steps)` 的 trajectory rows。
- 为每个 sample 生成稳定 crane order。
- 将 boolean、nullable numeric 和离散 task/weather 字段转换为数值 feature。
- 按 `max_nodes` padding，并输出 `node_mask`。
- 对缺失必需字段报错，对缺失可选字段使用文档化默认值并记录 warning。

不做：

- 不读取 pair future label 字段。
- 不构造边特征、邻接、轨迹标签或风险标签。
- 不改变可变塔吊策略；只消费 Task 08 的 `max_nodes` 和 crane order。

## 接口与数据结构（签名级别）

```python
class NodeFeatureBuilder:
    def __init__(self, *, feature_spec: StgnnFeatureSpec) -> None: ...

    def build(
        self,
        *,
        window: DatasetWindowIndexRow,
        tables: EpisodeTables,
        crane_order: Sequence[str],
        max_nodes: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return X_node [T_in, max_nodes, F_node], node_mask [max_nodes]."""
```

默认编码规则：

```text
bool -> 0.0/1.0
missing nullable numeric -> 0.0 plus warning
wind_direction_deg -> sin/cos; null -> 0.0/1.0 neutral
visibility_level -> stable ordinal code from known enum; unknown/null -> 0.0 plus warning
task_stage -> stable ordinal code; unknown/null -> 0.0 plus warning
has_task -> 1.0 when task_id is non-empty else 0.0
```

时间泄漏禁止规则：

```text
Allowed frame range: start_frame <= frame < start_frame + input_steps
Forbidden columns as node input:
  min_clearance_future_*, ttc_*, risk_level_[0-9]*s, collision_label_*
```

## 前置依赖

- Task 01 feature spec。
- Task 03 episode source loader。
- Task 08 variable crane strategy 提供 `crane_order` 和 `max_nodes`。

## 验收标准（具体、可测试）

- 对 3 台塔吊、2 个 input frame、默认 feature spec，输出 shape 为 `[2, max_nodes, node_feature_dim]`。
- `node_mask` 对真实塔吊为 `True`，padding 节点为 `False`。
- crane order 稳定；同一 episode 多个窗口使用相同顺序。
- 输出不包含 NaN/Inf。
- 只访问输入窗口帧；测试用 sentinel future frame 证明不会被读取。
- 必需字段缺失时抛 `TRAINING_E_SOURCE_SCHEMA_INVALID`。
- feature spec 中出现禁止 future label 字段时抛 `TRAINING_E_TIME_LEAKAGE`。

## 测试要点（正常 + 边界 + 异常）

正常：

- 完整 trajectory rows 生成数值矩阵。
- `wind_direction_deg=90` 转为 sin/cos。
- `load_attached=True` 转为 1.0。

边界：

- `load_weight_t=None` 生成 0.0 和 warning。
- padding 到大于实际 `num_cranes` 的 `max_nodes`。
- `visibility_level=None` 使用 unknown code。

异常：

- 缺少 `theta_sin`。
- feature spec 包含 `collision_label_5s`。
- 输入窗口某一帧缺少某台 crane。

## 依赖关系

依赖 Task 01、Task 03、Task 08。Task 10 依赖本任务。
