# Task 02：Pair Geometry Distance

## 任务目标

实现单帧、单对塔吊的精确几何距离计算，输出 jib-jib、jib-hook、hook-hook 的 raw distance 与扣除 geometry envelope 后的 clearance。

## 范围：做什么 / 不做什么

做：

- 新增 `backend/app/sim/offline_label.py` 中的几何距离函数。
- 复用并必要时修正 `backend/app/sim/collision.py` 中的 `segment_distance_3d()`、`point_segment_distance_3d()`。
- 计算塔臂-塔臂线段距离。
- 计算塔臂 i 到吊钩 j 的点线距离。
- 计算塔臂 j 到吊钩 i 的点线距离。
- 计算吊钩-吊钩点距离。
- 区分 `raw_distance` 和 `clearance`：`clearance = raw_distance - radius_a - radius_b`。
- 从四类对象距离中选出 `distance_min_raw_now_m`、`clearance_min_now_m`、nearest object。
- 对 `load_position` / 吊物摆动包络预留扩展点，但 MVP 不把 load 距离写进 K.2 固定字段。
- 对非法几何输入抛出 `OFFLINE_LABEL_E_INVALID_GEOMETRY`。

不做：

- 不计算未来窗口。
- 不计算 TTC、risk level 或 collision label。
- 不遍历 episode、frame 或所有 crane pair。
- 不写 Parquet。
- 不修改在线 `distance_between_cranes()` 的行为，除非为了复用提取纯几何 helper 且所有 H 测试保持通过。

## 接口与数据结构（签名级别）

建议接口：

```python
def compute_pair_geometry_distances(
    *,
    state_i: CraneState,
    state_j: CraneState,
    risk_config: RiskConfig,
) -> OfflinePairGeometryDistance:
    ...
```

辅助接口：

```python
def clearance_from_raw_distance(
    *,
    raw_distance_m: float,
    radius_a_m: float,
    radius_b_m: float,
) -> float:
    ...
```

```python
def point_distance_3d(point_a: Sequence[float], point_b: Sequence[float]) -> float:
    ...
```

```python
def pair_id(crane_id_a: str, crane_id_b: str) -> str:
    ...
```

输出映射：

```text
jib-jib raw:
  segment_distance_3d(state_i.root_position, state_i.tip_position,
                      state_j.root_position, state_j.tip_position)

jib-i hook-j raw:
  point_segment_distance_3d(state_j.hook_position,
                            state_i.root_position, state_i.tip_position)

jib-j hook-i raw:
  point_segment_distance_3d(state_i.hook_position,
                            state_j.root_position, state_j.tip_position)

hook-hook raw:
  point_distance_3d(state_i.hook_position, state_j.hook_position)
```

clearance 半径：

```text
jib-jib:
  raw - envelope.jib_radius_m - envelope.jib_radius_m

jib_i-hook_j:
  raw - envelope.jib_radius_m - envelope.hook_radius_m

jib_j-hook_i:
  raw - envelope.jib_radius_m - envelope.hook_radius_m

hook-hook:
  raw - envelope.hook_radius_m - envelope.hook_radius_m
```

`distance_min_raw_now_m` 应对应最小 clearance 的那一类对象，而不是单纯最小 raw distance。这样标签的 nearest object 与碰撞判定一致。

## 前置依赖

- Task 01 的 `OfflinePairGeometryDistance` 和 `OFFLINE_LABEL_E_INVALID_GEOMETRY`。
- `CraneState.root_position`、`tip_position`、`hook_position`、可选 `load_position`。
- `RiskConfig.geometry_envelope`。
- `backend/app/sim/collision.py` 中现有几何 helper。

## 验收标准（具体、可测试）

- 两条平行 3D 线段距离计算正确。
- 两条相交 3D 线段距离为 `0.0`。
- 点在线段投影内部时，点线距离等于垂直距离。
- 点在线段投影外部时，点线距离等于最近端点距离。
- hook-hook 距离使用欧氏 3D 距离。
- `clearance_jib_jib_now_m == raw - 2 * jib_radius_m`。
- `clearance_jib_i_hook_j_now_m == raw - jib_radius_m - hook_radius_m`。
- `clearance_hook_hook_now_m == raw - 2 * hook_radius_m`。
- 当 clearance 为负时不截断为 0；离线标签需要保留穿透深度。
- `clearance_min_now_m` 等于四类 clearance 的最小值。
- `nearest_object_i` / `nearest_object_j` 与最小 clearance 对应。
- `state_i.crane_id == state_j.crane_id` 时抛出 `OFFLINE_LABEL_E_INVALID_GEOMETRY`。
- 任一几何点不是 3 维、包含 NaN/Inf 或缺失时抛出 `OFFLINE_LABEL_E_INVALID_GEOMETRY`。

## 测试要点（正常 + 边界 + 异常）

- 正常：两塔塔臂平行且相距 5m，设置半径后 clearance 精确可算。
- 正常：jib_i 与 hook_j 最近，断言 min 字段选择 jib-hook。
- 正常：hook-hook 最近，断言 nearest object 为 hook/hook。
- 边界：线段退化为点时仍能计算点线/点点距离。
- 边界：raw distance 正好等于半径和时 clearance 为 0。
- 边界：raw distance 小于半径和时 clearance 为负。
- 异常：重复 crane_id。
- 异常：`hook_position=[1, 2]`。
- 异常：`tip_position=[math.nan, 0, 0]`。
- 回归：`pytest backend/app/tests/test_collision.py backend/app/tests/test_risk_online.py -v` 仍通过。

## 依赖关系

依赖 Task 01。Task 03 和 Task 04 依赖本任务的 per-frame pair distance 序列。
