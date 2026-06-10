# Task 05：任务可达性与载重预检查 Hook

## 任务目标

为 auto layout 和后续模块 D 的任务生成提供轻量级预检查：判断 material/work zones 是否至少能被布局中的塔吊覆盖，并判断 load type 的重量范围是否可能违反载重/力矩限制。

本任务仍属于模块 B 的边界，因为它只判断“某个布局是否具备任务生成的几何和机械可能性”，不生成具体 `Task`，不创建任务队列，也不推进任务状态机。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.5.3`、`0.5.4`、`0.5.6`、`模块 B.2` 和 `模块 D`。

## 任务范围

本任务实现：

- zone 几何采样或代表点提取。
- 判断 material zone 是否被至少一台塔吊作业半径覆盖。
- 判断 work zone 是否被至少一台塔吊作业半径覆盖。
- 判断 pickup/dropoff 支持的 load type 是否与场景 `load_types` 一致。
- 判断 load type 最大重量在候选半径下是否可能被吊起。
- 为 auto layout quality score 提供 precheck pass/fail 和 penalty。

本任务不实现：

- 具体 pickup/dropoff 点采样。
- `Task` 对象创建。
- easy/overlap/stress task 分布。
- planned_start_s、deadline、priority。
- attach/release 状态机。
- `TASK_E_001` / `TASK_E_002` 的最终任务失败策略。

这些由模块 D 实现。本任务只作为布局阶段预检查 hook。

## 建议代码位置

```text
backend/app/sim/layout_reachability.py
backend/app/tests/test_layout_reachability.py
```

## 输入与输出

输入：

- `CraneConfig[]`
- `ScenarioConfig.site.material_zones`
- `ScenarioConfig.site.work_zones`
- `ScenarioConfig.load_types`
- `ScenarioConfig.tasks`
- `dict[str, CraneModelSpec]`

输出：

```text
LayoutReachabilityReport:
  can_generate_tasks: bool
  material_zone_reports: list
  work_zone_reports: list
  load_type_reports: list
  warnings: list
  blocking_reasons: list
```

每个 zone report 至少包含：

```text
zone_id
zone_type
reachable_by_crane_ids
supported_load_types
representative_points_checked
```

每个 load type report 至少包含：

```text
load_type
max_weight_t
reachable_by_crane_ids
min_capacity_margin_t
```

## 几何规则

M1 初版推荐：

- box zone 使用 center 和 corners 作为代表点。
- polygon zone 使用 centroid 和 vertices 作为代表点。
- 如果 zone 有 `z_range_m`，代表点 z 使用区间中点；否则 material zone 使用 `tasks.fallback_pickup_z_m`，work zone 使用 `tasks.fallback_dropoff_z_range_m` 中点。
- 某塔吊覆盖代表点的条件：

```text
trolley_r_min_m <= horizontal_distance(base_xy, point_xy) <= trolley_r_max_m
hook_h_min_world_m <= point_z <= hook_h_max_world_m
```

- load type 可吊起条件：

```text
capacity_at_radius_t(horizontal_distance) >= load_type.weight_range_t[1]
```

说明：

- 本任务用最大重量做保守预检查，避免天然超载任务进入生成阶段。
- 如果只允许部分重量范围可吊，可以作为 warning，不建议作为 pass；模块 D 也可以后续选择采样较轻重量，但必须显式记录。

## 与模块 D 的边界

本任务可以说：

```text
这个布局至少存在可达 material/work zone 和 load type 组合。
```

本任务不能说：

```text
已经生成了任务。
任务一定可完成。
某个具体 task_id 应分配给某台塔吊。
attach/release 会成功。
deadline 合理。
```

如果预检查失败：

- 在 auto layout 阶段可作为 `task_reachability_precheck_failed` 继续重采样。
- 在最终布局仍失败时，auto layout 返回 `LAY_E_001`。
- manual layout 阶段只把该失败写入 `LayoutReachabilityReport` 和 layout warning，不由模块 B 直接生成 `TASK_E_*`。
- 模块 D 在真正生成 `Task` 时必须把 pickup/dropoff 不可达、天然超载或超力矩映射为 `TASK_E_001` / `TASK_E_002`，或按任务生成策略重新采样；不可把明显不可达或天然超载的任务放入正常 episode。

## 测试要求

建议测试文件：

```text
backend/app/tests/test_layout_reachability.py
```

必测场景：

- material zone center 在作业半径内时 report 可达。
- material zone 完全超出所有塔吊半径时 report 不可达。
- work zone z 高于 `hook_h_max_world_m` 时 report 不可达。
- load type 最大重量超过 `capacity_at_radius_t` 时 report 阻塞。
- material zone `load_types` 引用了不存在的 load type 时 warning 或 blocking reason 明确。
- work zone `accepted_load_types` 与 material zone 无交集时 blocking reason 明确。
- manual layout 调用 precheck 时只产生 warning/report，不生成 `TASK_E_001` 或 `TASK_E_002`。
- 多塔场景下 report 正确列出可达 crane ids。
- precheck 不创建 `Task` 字段，如 `task_id`、`status`、`task_stage`。

推荐命令：

```bash
pytest backend/app/tests/test_layout_reachability.py -v
```

## 验收标准

- auto layout 可以用该 hook 避免生成明显无法服务任务区域的布局。
- 载重/力矩预检查使用 `CraneModelSpec.capacity_at_radius_t`，不是单一 `max_load_t`。
- 报告只表达布局可行性，不越界生成任务。
- 不可达原因可被写入布局 diagnostics。
