# Task 06：轨迹标签 Y_traj 与风险标签 Y_risk 构造

## 任务目标

从权威 trajectory 和 offline risk label 字段构造预测目标 `Y_traj` 与 `Y_risk`，保证标签只来自 L/K 落盘真值，不重算、不篡改、不使用在线风险替代离线标签。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/training/labels.py`。
- 从预测窗口 `[start_frame + input_steps, start_frame + input_steps + pred_steps)` 构造 `Y_traj`。
- 从 `pair_risks.parquet` 指定 anchor frame 构造 `Y_risk`。
- 支持 `risk_label_horizons_s` 中的 5s、10s、15s 等 horizon。
- 生成风险标签 mask，支持单塔吊或缺 pair 的合法空风险标签。
- 校验离线标签字段存在、类型合法、collision label 为 0/1。

不做：

- 不重算 min clearance、TTC、risk level 或 collision label。
- 不从预测窗口后的 trajectory 扫描未来风险。
- 不把 `risk_level_now` 当作未来风险 label。
- 不修改 source Parquet。

## 接口与数据结构（签名级别）

```python
class LabelBuilder:
    def __init__(self, *, feature_spec: StgnnFeatureSpec) -> None: ...

    def build_traj(
        self,
        *,
        window: DatasetWindowIndexRow,
        tables: EpisodeTables,
        crane_order: Sequence[str],
        max_nodes: int,
    ) -> np.ndarray:
        """Return Y_traj [T_pred, max_nodes, traj_target_dim]."""

    def build_risk(
        self,
        *,
        window: DatasetWindowIndexRow,
        tables: EpisodeTables,
        crane_order: Sequence[str],
        max_nodes: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return Y_risk [H, max_nodes, max_nodes, risk_target_dim], risk_mask [H, max_nodes, max_nodes]."""
```

风险 anchor 规则：

```text
anchor_frame = start_frame + input_steps - 1
Y_risk[horizon] reads only pair_risks rows where frame == anchor_frame.
Required columns for each horizon:
  risk_level_{horizon}, collision_label_{horizon},
  min_clearance_future_{horizon}_m, ttc_{horizon}_s
```

轨迹标签规则：

```text
prediction_start = start_frame + input_steps
prediction_end = prediction_start + pred_steps
Y_traj reads frames [prediction_start, prediction_end)
```

## 前置依赖

- Task 01 feature spec。
- Task 03 episode source loader。
- Task 08 variable crane strategy。

## 验收标准（具体、可测试）

- 对合法 tiny episode，`Y_traj` shape 为 `[pred_steps, max_nodes, traj_target_dim]`。
- 对 3 台塔吊、3 个 horizon，`Y_risk` shape 为 `[3, max_nodes, max_nodes, risk_target_dim]`。
- 轨迹标签使用预测窗口，不读取输入窗口外其他字段。
- 风险标签使用 anchor frame 的 offline columns。
- `risk_level_5s` 等字符串稳定编码为数值 code。
- collision label 只能是 0/1。
- horizon 列缺失时抛 `TRAINING_E_LABEL_MISSING`。
- 尝试启用 `risk_level_now` 作为未来 label 时抛 `TRAINING_E_LABEL_MISSING` 或配置校验错误。

## 测试要点（正常 + 边界 + 异常）

正常：

- 预测窗口 2 帧、3 台塔吊的 trajectory label。
- 5s/10s/15s 风险 label，包含 safe/high/collision。
- `ttc_*_s=None` 转为 sentinel 并由 mask 或 feature convention 标识。

边界：

- 单塔吊 episode 输出空风险 mask，不报错。
- 某 pair 在 anchor frame 缺失时该 pair risk mask 为 false 或按 strict options 报错，策略必须固定。
- horizon 顺序按 `risk_label_horizons_s` 保持。

异常：

- 缺 `risk_level_10s`。
- `collision_label_5s=2`。
- prediction frame 缺少某台 crane。
- 从 future trajectory 现算 label 的 helper 不存在，静态测试保证未导入 K label generator。

## 依赖关系

依赖 Task 01、Task 03、Task 08。Task 10 依赖本任务。
