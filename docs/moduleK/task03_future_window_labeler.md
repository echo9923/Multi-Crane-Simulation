# Task 03：Future Window Labeler

## 任务目标

基于完整真实轨迹的 per-pair distance 序列，计算任意未来窗口内的最小 clearance、TTC、risk level 和 collision label。

## 范围：做什么 / 不做什么

做：

- 在 `backend/app/sim/offline_label.py` 中实现未来窗口标签函数。
- 给定当前帧 index、pair 时序距离和 `window_s`，扫描 `[current_time, current_time + window_s]` 内所有真实轨迹采样。
- 计算 `min_clearance_future_m`。
- 计算 `ttc_s`：窗口内首次进入 `d_safe_effective_m` 或碰撞条件的相对时间。
- 计算 `risk_level`：基于未来最小 clearance 和 TTC 映射到 `safe/low/medium/high/near_miss/collision`。
- 计算 `collision_label`：窗口内任意 `clearance <= 0` 即为 `1`。
- 输出 `OfflineFutureWindowLabel(used_future_truth=True)`。
- 支持 `RiskConfig.future_windows_s` 中的 `5/10/15` 秒及自定义窗口。

不做：

- 不计算单帧几何距离；输入来自 Task 02。
- 不遍历所有 crane pair；完整遍历由 Task 04 完成。
- 不写 `OfflineRiskLabel` 的显式 K.2 字段；由 Task 04 组装。
- 不使用在线预测、模型预测或 `OnlineRisk.d_hat_min_m`。
- 不外推超过 episode 末尾的轨迹；窗口自然截断到已有真实轨迹。

## 接口与数据结构（签名级别）

建议内部时序对象：

```python
class OfflinePairGeometryDistanceAtTime(RiskBaseModel):
    schema_version: str = OFFLINE_LABEL_SCHEMA_VERSION
    frame: int = Field(ge=0)
    time_s: float = Field(ge=0)
    geometry: OfflinePairGeometryDistance
```

核心接口：

```python
def compute_future_window_label(
    *,
    current_index: int,
    pair_series: Sequence[OfflinePairGeometryDistanceAtTime],
    window_s: float,
    risk_config: RiskConfig,
    d_safe_effective_m: float | None = None,
) -> OfflineFutureWindowLabel:
    ...
```

批量接口：

```python
def compute_future_window_labels(
    *,
    current_index: int,
    pair_series: Sequence[OfflinePairGeometryDistanceAtTime],
    windows_s: Sequence[float],
    risk_config: RiskConfig,
    d_safe_effective_m: float | None = None,
) -> dict[str, OfflineFutureWindowLabel]:
    ...
```

`d_safe_effective_m` 默认值：

```text
risk_config.thresholds_m.high
```

如果实现阶段选择引入 weather/wind 序列，则可传入按帧有效安全距离；本任务 MVP 只使用 risk config 基础 high 阈值，因为 K 当前输入未包含 weather trajectory。

TTC 规则：

```text
current_time = pair_series[current_index].time_s
window_end = current_time + window_s
samples = pair_series entries where current_time <= time_s <= window_end

ttc_s = first(sample.time_s - current_time)
        where sample.geometry.clearance_min_now_m <= d_safe_effective_m

if no sample enters d_safe_effective_m:
    ttc_s = None
```

collision 规则：

```text
collision_label = 1 if min_clearance_future_m <= 0 else 0
```

risk level 规则：

```text
if min_clearance_future_m <= 0:
    collision
elif min_clearance_future_m <= thresholds_m.near_miss:
    near_miss
elif min_clearance_future_m <= thresholds_m.high:
    high
elif ttc_s is not None:
    high
elif min_clearance_future_m <= thresholds_m.medium:
    medium
elif min_clearance_future_m <= thresholds_m.low:
    low
else:
    safe
```

阈值含义沿用 H 的 `classify_risk_level()`，但输入使用真实未来最小 clearance。

## 前置依赖

- Task 01 的 `OfflineFutureWindowLabel`、`RiskConfig.future_windows_s`。
- Task 02 的 `OfflinePairGeometryDistance`。
- `RiskThresholdsConfig` 和 `RiskLevel`。

## 验收标准（具体、可测试）

- `window_s <= 0` 抛出 `OFFLINE_LABEL_E_INVALID_WINDOW`。
- `current_index` 越界抛出 `OFFLINE_LABEL_E_MISSING_FRAME` 或明确 ValueError。
- pair series 为空抛出 `OFFLINE_LABEL_E_EMPTY_TRAJECTORY`。
- pair series 的 frame 递增且 time_s 单调；否则抛出 `OFFLINE_LABEL_E_MISSING_FRAME`。
- 未来窗口包含当前帧。
- 未来窗口超出 episode 尾部时，使用 episode 剩余真实帧，不补点、不外推。
- `min_clearance_future_m` 等于窗口内最小 `clearance_min_now_m`。
- 窗口内第一次 `clearance <= d_safe_effective_m` 的相对时间成为 `ttc_s`。
- 若窗口内从未进入 `d_safe_effective_m`，`ttc_s is None`。
- 若当前帧已经进入 `d_safe_effective_m`，`ttc_s == 0.0`。
- 若窗口内任一帧 `clearance <= 0`，`collision_label == 1` 且 `risk_level == "collision"`。
- `used_future_truth` 恒为 `True`。
- 批量窗口输出包含规范 key，例如 `5s`、`10s`、`15s`。

## 测试要点（正常 + 边界 + 异常）

- 正常：clearance 序列 `[8, 6, 4, 2]`，5s 窗口最小值为 2。
- 正常：clearance 在第 3 秒首次小于 high 阈值，`ttc_s == 3.0`。
- 正常：5s 无碰撞、10s 有碰撞，两个窗口 collision label 不同。
- 边界：当前帧即碰撞，TTC 为 0 且 collision label 为 1。
- 边界：episode 剩余时长小于 window_s，仍正常返回。
- 边界：采样时间不等间隔，TTC 使用真实 `time_s` 差值。
- 异常：负窗口、空序列、非单调 time、重复 frame。
- 防泄漏：测试名称和对象明确包含 `used_future_truth=True`，但只在 K schema 中出现。

## 依赖关系

依赖 Task 01 和 Task 02。Task 04 使用本任务为每条 `OfflineRiskLabel` 填充所有未来窗口字段。
