# Task 04：Neighbor Visibility Filter

## 任务目标

根据模块 E 的 `WeatherVisibilityContext` 对候选邻塔做可见性筛选、距离加噪和 hook 信息隐藏，确保 observation 只呈现司机可见的邻塔当前状态。

## 范围

做：

- 实现 `build_visible_neighbors()`。
- 从 `neighbor_map[observer]` 取得候选邻塔。
- 用 observer hook 与 target hook 的当前距离判断是否在 `neighbor_visibility_radius_m` 内。
- 使用 `build_visibility_sampling_key()` 对距离噪声和 hook 隐藏做稳定采样。
- 输出相对方向、带噪声且圆整后的距离、距离等级、邻塔当前运动、载荷可见状态、当前 task stage、是否处于重叠区。

不做：

- 不计算布局层面的邻塔关系。
- 不读取邻塔任务队列、任务目标、deadline 或 task_id。
- 不计算风险或最小距离真值。

## 接口与数据结构

```python
def build_visible_neighbors(
    *,
    observer_state: CraneState,
    states_by_id: dict[str, CraneState],
    neighbor_ids: list[str],
    visibility: WeatherVisibilityContext,
    decision_time_bucket: int,
) -> list[VisibleNeighbor]:
    ...
```

## 前置依赖

- Task 01 schema。
- 模块 E `WeatherVisibilityContext`、`build_visibility_sampling_key()`。

## 验收标准

- 超出可见半径的候选邻塔不会进入 observation。
- 同一 seed、bucket、observer/target 的噪声和 hook hide 结果稳定。
- 不同 observer/target 或 purpose 的采样可不同。
- 距离噪声只影响 observation 输出，不修改 `CraneState`。
- hidden hook 时仍可显示邻塔大致方向/距离，但 `hook_visible=False` 且 hook 高度等精确信息为 `None`。
- `VisibleNeighbor.model_dump()` 不包含 `task_id`、`deadline_s`、`planned_start_s`、目标坐标、offline TTC 或 future min distance。

## 测试要点

- 正常：good visibility 下近邻可见，远邻不可见。
- 边界：距离刚好等于可见半径、hide_hook_prob 为 0 和 1。
- 异常：neighbor id 在 states 中缺失时抛 `ObservationBuildError`。
- 防泄漏：序列化 payload 字符串中不出现禁用字段。

