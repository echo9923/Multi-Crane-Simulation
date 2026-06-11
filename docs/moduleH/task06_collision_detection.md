# Task 06：Collision Detection and Episode Termination

## 任务目标

实现碰撞检测与终止层，在当前几何包络已经相交或达到碰撞阈值时记录 `CollisionEvent`，返回 `episode_status="failed_collision"`，要求调度器立即终止 episode 且不生成碰撞后轨迹。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/sim/collision.py`。
- 实现 2D 线段相交检测，用于 jib-jib 水平投影交叉用例。
- 实现点到线段、线段到线段距离计算。
- 结合高度差和 `RiskConfig.geometry_envelope` 判断 jib-jib、jib-hook、hook-hook、load 相关碰撞。
- 将 `RiskPairResult.risk_level="collision"` 转换为 `CollisionEvent`。
- 在 `apply_safety_pipeline()` 末尾汇总碰撞结果。
- 返回 `SafetyPipelineResult.episode_status="failed_collision"`。

不做：

- 不推进 episode 主循环。
- 不写碰撞后的状态。
- 不负责删除已经生成的历史轨迹。
- 不做高精度吊载摆动碰撞仿真。
- 不生成离线标签。

## 接口与数据结构（签名级别）

```python
def detect_collisions(
    *,
    crane_states: list[CraneState],
    crane_configs: list[CraneConfig],
    risk_config: RiskConfig,
    source_snapshot_id: str,
    time_s: float,
) -> CollisionEvent | None:
    ...

def detect_pair_collision(
    *,
    state_a: CraneState,
    config_a: CraneConfig,
    state_b: CraneState,
    config_b: CraneConfig,
    risk_config: RiskConfig,
    source_snapshot_id: str,
    time_s: float,
) -> CollisionEvent | None:
    ...

def segments_intersect_2d(
    a0: tuple[float, float],
    a1: tuple[float, float],
    b0: tuple[float, float],
    b1: tuple[float, float],
) -> bool:
    ...

def segment_distance_3d(
    a0: list[float],
    a1: list[float],
    b0: list[float],
    b1: list[float],
) -> float:
    ...

def point_segment_distance_3d(
    point: list[float],
    segment_start: list[float],
    segment_end: list[float],
) -> float:
    ...
```

碰撞阈值 MVP：使用 `geometry_envelope` 包络半径之和作为碰撞距离；例如 hook-hook 碰撞距离为 `2 * hook_radius_m`，jib-hook 为 `jib_radius_m + hook_radius_m`。

## 前置依赖

- Task 01 的 `CollisionEvent` 和 `SafetyPipelineResult`。
- Task 04 的几何距离语义。
- `RiskConfig.geometry_envelope`。
- `CraneState.root_position`、`tip_position`、`hook_position`、`load_position`。

## 验收标准（具体、可测试）

- 两条 2D 线段交叉时 `segments_intersect_2d()` 返回 True。
- 两条 2D 线段平行不交时返回 False。
- 端点接触按碰撞候选处理。
- hook-hook 距离小于等于 `2 * hook_radius_m` 时生成 `CollisionEvent`。
- jib-hook 距离小于等于 `jib_radius_m + hook_radius_m` 时生成 `CollisionEvent`。
- jib-jib 3D 距离小于等于 `2 * jib_radius_m` 时生成 `CollisionEvent`。
- 高度差足够大且 3D 距离超过包络时不碰撞，即使水平投影交叉。
- 多对塔吊碰撞时返回时间和 crane_id 排序稳定的第一条 event，或按实现文档固定排序。
- `CollisionEvent.episode_status` 固定为 `failed_collision`。
- `SafetyPipelineResult` 包含 collision 时 `episode_status="failed_collision"`。
- 碰撞后不生成新的 `ControlTarget` 或物理状态的要求由 J/I 测试验证，H 只返回终止信号。

## 测试要点（正常 + 边界 + 异常）

- 正常：jib-jib 交叉碰撞、hook-hook 碰撞、jib-hook 碰撞。
- 边界：端点接触、距离正好等于包络阈值、水平交叉但高度安全。
- 异常：重复 crane_id、缺失 position 三维向量、风险配置包络半径非法由 schema 拒绝。
- 合同：碰撞 event 能被 `SafetyPipelineResult.events` 和 `collision` 字段同时追溯。
