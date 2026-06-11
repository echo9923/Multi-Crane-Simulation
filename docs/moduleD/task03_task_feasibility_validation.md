# Task 03：任务可达性、禁区、载重与力矩校验

## 任务目标

对具体 `Task` 执行启动前可行性校验，确保进入正常 episode 的任务不会天然不可达、天然超载、天然超力矩或目标点落入 forbidden zone。

模块 B 的 reachability precheck 只说明“布局大体能服务任务区域”；本任务负责具体 task 级别的最终判断。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.5.4`、`0.5.6`、`0.5.7`、`0.7.5`、`模块 D.3`、`模块 D.7` 和错误矩阵。

## 任务范围

本任务实现：

- pickup/dropoff 对 assigned crane 的几何可达性校验。
- pickup/dropoff site boundary 校验。
- pickup/dropoff forbidden zone 校验。
- load type 合法性校验。
- zone 支持 load type 校验。
- pickup/dropoff 半径处的载重/力矩校验。
- `TASK_E_001` 和 `TASK_E_002` 错误映射。
- `TaskFeasibilityReport`。

本任务不实现：

- zone 内随机采样。
- 队列启动。
- runtime attach/release 判定。
- 基础机械安全层的 runtime 限载干预。
- forbidden zone runtime violation 事件。

## 建议代码位置

```text
backend/app/sim/task_feasibility.py
backend/app/tests/test_task_feasibility.py
```

## 输入与输出

输入：

- `Task`
- assigned `CraneConfig`
- `ScenarioConfig.site`
- `ScenarioConfig.load_types`
- material/work zone index

输出：

```text
TaskFeasibilityReport:
  task_id: str
  crane_id: str
  feasible: bool
  pickup_reachable: bool
  dropoff_reachable: bool
  boundary_clear: bool
  forbidden_zone_clear: bool
  load_type_supported: bool
  pickup_capacity_margin_t: float | null
  dropoff_capacity_margin_t: float | null
  blocking_error_code: str | null
  blocking_reasons: list[str]
  warnings: list[dict]
```

## 几何可达性规则

对任一目标点 `p`：

```text
radius_m = horizontal_distance(crane.base, p)

trolley_r_min_m <= radius_m <= trolley_r_max_m
hook_h_min_world_m <= p.z <= hook_h_max_world_m
```

pickup 和 dropoff 都必须对 assigned crane 可达。

不可达映射：

```text
TASK_E_001
```

常见 reason：

```text
pickup_outside_radius
dropoff_outside_radius
pickup_height_unreachable
dropoff_height_unreachable
unknown_zone
invalid_zone_geometry
```

## 工地边界规则

pickup/dropoff 必须落在 `site.boundary` 内：

```text
x_min <= point.x <= x_max
y_min <= point.y <= y_max
z_min <= point.z <= z_max
```

边界阻塞映射：

```text
TASK_E_001
```

常见 reason：

```text
pickup_outside_site_boundary
dropoff_outside_site_boundary
```

## 禁区规则

task generation 阶段：

- pickup/dropoff 不得落入 forbidden zone。
- 即使 `forbidden_zone_policy.mode=task_only`，任务点也不得在 forbidden zone 内。
- 如果 `mode=hard`，同样直接阻塞。

禁区阻塞映射：

```text
TASK_E_001
```

runtime 中吊钩/载荷进入禁区的记录或硬限制不归本任务；由安全层、风险/事件或调度器处理。

## load type 支持规则

候选任务必须满足：

```text
task.load_type in scenario.load_types
task.load_type in pickup_zone.load_types, if pickup_zone declares load_types
task.load_type in dropoff_zone.accepted_load_types, if dropoff_zone declares accepted_load_types
```

失败映射：

```text
TASK_E_001
```

reason：

```text
unknown_load_type
pickup_zone_rejects_load_type
dropoff_zone_rejects_load_type
```

## 载重与力矩规则

对 pickup 和 dropoff 半径分别检查：

```text
capacity_at_radius_t(radius_m) >= task.load_weight_t
```

其中 `capacity_at_radius_t` 必须来自 `CraneModelSpec` 或 `CraneConfig.model`，不能只使用单一 `max_load_t`。

失败映射：

```text
TASK_E_002
```

reason：

```text
pickup_over_capacity
dropoff_over_capacity
pickup_moment_limit_exceeded
dropoff_moment_limit_exceeded
```

说明：

- 如果 `load_weight_t` 在 pickup 可吊但 dropoff 不可吊，任务仍不可进入正常 episode。
- 如果 load type 最大重量不可吊，但当前采样重量可吊，该具体任务可以通过；生成报告应记录采样重量。
- 如果配置策略要求保守使用最大重量，则生成器应在 Task 02 采样前过滤掉该 load type。

## startup、resample 与 skipped 策略

auto generation：

- 单次候选失败时返回 report 给 Task 02 重采样。
- 超过最大尝试次数仍无法生成足够任务时，返回 startup blocking error。

manual generation：

- 如果用户提供的是模板，D 可以重采样具体点。
- 如果用户提供的是显式坐标，默认 startup error，不建议静默修改用户坐标。
- 若未来新增 `invalid_manual_task_policy=skip`，才允许把该任务标记为 `skipped`，并写入 report。

正常 episode 中不得出现：

- `TASK_E_001` 的 active task。
- `TASK_E_002` 的 active task。

## 与模块 B 的边界

模块 B Task 05 可以说：

```text
布局存在可服务 zone 的可能性。
```

模块 D Task 03 必须说：

```text
这个具体 task 的 pickup/dropoff/load 对 assigned crane 是否可执行。
```

D 可以复用 B 的几何工具和 capacity 函数，但错误归属为 `TASK_*`。

## 测试要求

建议测试文件：

```text
backend/app/tests/test_task_feasibility.py
```

必测场景：

- pickup 在半径内且高度内时通过。
- pickup 超出 `trolley_r_max_m` 返回 `TASK_E_001`。
- dropoff 低于 `hook_h_min_world_m` 返回 `TASK_E_001`。
- pickup/dropoff 超出 site boundary 返回 `TASK_E_001`。
- pickup 落入 forbidden zone 返回 `TASK_E_001`。
- unknown load type 返回 `TASK_E_001`。
- pickup zone 不支持 load type 返回 `TASK_E_001`。
- dropoff zone 不接受 load type 返回 `TASK_E_001`。
- pickup 半径处 capacity 小于 `load_weight_t` 返回 `TASK_E_002`。
- dropoff 半径处 capacity 小于 `load_weight_t` 返回 `TASK_E_002`。
- 校验使用 load chart/capacity_at_radius，而不是 `max_load_t`。
- B 的 precheck 通过但具体任务不可达时，D 仍返回 task-level failure。

推荐命令：

```bash
pytest backend/app/tests/test_task_feasibility.py -v
pytest backend/app/tests/test_layout_reachability.py -v
```

## 验收标准

- 具体任务进入 episode 前都有 task-level 可行性 report。
- 具体任务点必须在 site boundary 内。
- 不可达与禁区错误稳定映射到 `TASK_E_001`。
- 天然超载或超力矩稳定映射到 `TASK_E_002`。
- 错误对象包含 task_id、crane_id、point、radius、capacity margin 和 reason。
