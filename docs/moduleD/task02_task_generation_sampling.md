# Task 02：任务生成、采样与分配

## 任务目标

根据场景配置、塔吊布局、zone、load type 和 `seeds.task` 生成每台塔吊独立任务队列。生成器只给出任务目标和任务压力条件，不给出操作路线，不预设 LLM 会怎样避让或完成任务。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.5.6`、`0.5.13`、`模块 D.1-D.3`、`模块 D.7` 和 `15.3`。

## 任务范围

本任务实现：

- deterministic task RNG。
- 每台塔吊生成 `num_tasks_per_crane` 个普通任务。
- `easy_task`、`overlap_task`、`stress_task` 分布采样。
- pickup 从 material zones 采样。
- dropoff 从 work zones 采样。
- load type、load weight、priority、deadline、planned_start 的采样。
- manual generation mode 的模板转任务。
- `TaskGenerationReport`。

本任务不实现：

- 最终可行性判定细节，归 Task 03。
- 队列激活和 runtime scheduling，归 Task 04。
- attach/release 状态机，归 Task 05。
- risk label 或碰撞制造。

## 建议代码位置

```text
backend/app/sim/task_generation.py
backend/app/tests/test_task_generation.py
```

## 输入与输出

输入：

- `ResolvedConfig.seeds.task`
- `ScenarioConfig.tasks`
- `ScenarioConfig.site.material_zones`
- `ScenarioConfig.site.work_zones`
- `ScenarioConfig.site.forbidden_zones`
- `ScenarioConfig.site.boundary`
- `ScenarioConfig.load_types`
- `CraneConfig[]`
- 可选 `LayoutReachabilityReport`

输出：

```text
TaskGenerationResult:
  queues: list[TaskQueue]
  tasks: list[Task]
  report: TaskGenerationReport
```

`TaskGenerationReport` 至少包含：

```text
schema_version
seed
num_cranes
num_tasks_total
num_tasks_by_type
num_resample_attempts
warnings
blocking_errors
```

## 生成流程

推荐流程：

```text
1. 初始化 RNG(seed=ResolvedConfig.seeds.task)。
2. 为每台 crane 创建空 TaskQueue。
3. 根据 task_type_distribution 为每个任务位采样 task_type。
4. 根据 task_type 选择 pickup/dropoff zone 候选。
5. 在 zone 内采样 pickup/dropoff 点。
6. 根据 zone 支持类型交集采样 load_type。
7. 在 load type weight_range_t 内采样 load_weight_t。
8. 根据 priority_distribution 采样 priority。
9. 根据 task_type 和 priority 生成 deadline_s。
10. 根据 queue_policy 预先写入 planned_start_s 或 null。
11. 调用 Task 03 的可行性校验；失败则按策略重采样。
12. 写入 TaskQueue，生成 report。
```

同一 resolved config 和同一 seed 必须得到完全相同的任务列表、顺序、ID 和采样值。

## Task ID 规则

推荐格式：

```text
T_<crane_id>_<NNN>
```

示例：

```text
T_C1_001
T_C1_002
T_C2_001
```

恢复任务使用：

```text
R_<crane_id>_<source_task_id>
```

恢复任务由 Task 06 创建，不由本任务生成。

## zone 采样规则

box zone：

- 在 `center +/- size/2` 的 x/y 范围内均匀采样。
- z 使用 `z_range_m` 内采样；若无 `z_range_m`，material 使用 `fallback_pickup_z_m`，work 使用 `fallback_dropoff_z_range_m`。

polygon zone：

- 初版可使用 rejection sampling：在 polygon bounding box 内采点，并用 point-in-polygon 判断。
- z 规则同 box zone。

fallback：

- zone 只有 center 时，直接使用 center x/y。
- zone 缺少可采样几何时，返回 `TASK_E_001` blocking error，不默默使用 `[0,0,z]` 作为真实任务点。

boundary：

- 采样出的 pickup/dropoff 必须落在 `site.boundary` 内。
- zone 部分越界时，采样器应 rejection sample 到 boundary 内的有效区域。
- zone 完全越界或在最大尝试次数内无法得到 boundary 内点时，返回 `TASK_E_001`。

## load type 采样规则

候选集合：

```text
candidate_load_types =
  material_zone.load_types
  ∩ work_zone.accepted_load_types
  ∩ scenario.load_types.keys()
```

如果 material/work zone 未显式声明类型，则视为支持全部 `scenario.load_types`。

如果交集为空：

- auto generation：重采样 zone pair。
- manual generation：默认返回 `TASK_E_001`；只有显式 `invalid_manual_task_policy=skip` 时才允许标记该模板 skipped。

`load_weight_t` 在 `LoadTypeConfig.weight_range_t` 内采样。Task 03 会检查该重量在 pickup/dropoff 半径处是否满足载重/力矩限制。

## easy_task

目标：

- 生成基础可达任务，用于验证单塔移动、对准、挂载、运输、卸载流程。
- 尽量避免任务点落在多塔重叠区核心位置。
- 默认 deadline 较宽松。

推荐采样：

- 优先选择只被目标塔吊覆盖，或距离其他塔吊作业半径边缘较远的 zone/point。
- pickup/dropoff 水平距离不宜过短，避免任务没有移动阶段。
- pickup/dropoff 不得天然贴近禁区边界。

## overlap_task

目标：

- 让 pickup 或 dropoff 位于多塔作业半径重叠区附近，制造自然交互背景。
- 不预设危险结果。

推荐采样：

- 至少一个点满足被目标塔吊和另一台塔吊覆盖。
- 另一个点可普通可达。
- planned_start 可按 queue policy 生成，不强制同步。

## TaskOverlapRegion 来源

M1 初版由模块 D 从 `CraneConfig[]` 派生轻量 `TaskOverlapRegion`，只用于任务采样：

```text
TaskOverlapRegion:
  region_id
  crane_ids
  approximate_center_xy
  candidate_material_zone_ids
  candidate_work_zone_ids
```

派生规则：

- 两台或多台塔吊的作业圆环在平面上有交叠，即可形成候选 overlap region。
- region 的 material/work zone 候选来自该 region 附近且能被相关塔吊覆盖的 zones。
- 该对象不写回 `LayoutDiagnostics`，不作为模块 B 的权威布局诊断。
- 该对象不表示危险，只表示任务采样的多塔交互背景。

如果某场景无法派生 overlap region：

- `overlap_task` 和 `stress_task` 应重采样为可生成类型，或在超过尝试次数后返回 `TASK_E_001`。
- report 必须记录 `no_task_overlap_region`。

## stress_task

目标：

- 在空间和时间上制造压力，使多台塔吊自然靠近同一重叠区域或相邻路径。
- 不预设操作轨迹，不强制碰撞，不通过穿模制造风险。

允许做法：

- 多台塔吊的任务目标靠近同一 overlap zone。
- 多台塔吊的 planned_start_s 接近。
- deadline_s 比 easy_task 更紧。
- 任务路径更容易交叉。

禁止做法：

- 不直接指定 LLM 路线。
- 不指定“必须同时到达某点”。
- 不设置天然不可达或天然超载任务。
- 不修改物理状态制造风险。

## planned_start_s 生成

`queue_policy.start_mode=simultaneous`：

```text
每台塔吊第一个任务 planned_start_s = 0。
后续任务 planned_start_s = null，由 inter_task_delay_s 控制。
```

`queue_policy.start_mode=staggered`：

```text
每台塔吊第一个任务 planned_start_s 从 initial_start_jitter_s 采样。
后续任务 planned_start_s = null。
```

`queue_policy.start_mode=scheduled`：

```text
当前 M1 schema 中 manual task 模板没有 planned_start_s，D 按 deterministic schedule 生成。
若后续扩展 ManualTaskInput.planned_start_s，则优先使用显式值。
```

注意：`planned_start_s` 是 episode 绝对时间。

## deadline_s 生成

`deadline_s` 是相对任务实际开始时刻的建议完成时长。

推荐初版：

- `easy_task`：宽松。
- `overlap_task`：中等。
- `stress_task`：更紧。
- `priority=high` 可进一步缩短。

具体数值可先由配置默认值或内部常量给出，但每次运行必须写入 generated Task，保证 replay 可复现。

## manual generation mode

当前 `ManualTaskInput` 包含：

```text
task_id
task_type
pickup_zone_id
dropoff_zone_id
load_type
priority
```

因此 M1 初版 manual mode 的语义是“手写任务模板”，不是完整坐标任务。D 应：

- 保留手写 `task_id`、`task_type`、zone 和 priority。
- 若模板包含未来扩展字段 `crane_id`，直接使用该 crane。
- 若当前 schema 没有 `crane_id`，必须按 deterministic assignment 规则选择一台可行塔吊。
- 在指定 zone 内使用 task seed 采样具体 pickup/dropoff。
- 使用指定 load_type。
- 对生成后的具体任务执行 Task 03 校验。

当前 schema 下的 deterministic assignment 推荐规则：

```text
1. 对所有 CraneConfig 按 crane_id 排序。
2. 对每台 crane 尝试生成并校验该 manual template 的具体任务。
3. 收集可行 crane ids。
4. 如果为空，返回 TASK_E_001；只有显式 `invalid_manual_task_policy=skip` 时才标记 skipped。
5. 如果只有一台，分配给该 crane。
6. 如果多台，使用 seeds.task + task_id 稳定选择一台。
```

manual task 分配结果必须写入最终 `Task.crane_id` 和对应 `TaskQueue`。

如果后续扩展 manual task 允许显式 pickup/dropoff 坐标、planned_start_s 或 crane_id，D 必须直接消费这些字段并执行 Task 03 校验；显式坐标不得被静默重采样。

## 重采样策略

自动生成失败时：

```text
unreachable -> resample point/zone
forbidden zone -> resample point
unknown load type -> resample zone/load type
over capacity -> resample weight/point/load type
```

达到每个任务的最大尝试次数后：

- 如果无法生成足够任务，返回 startup blocking error。
- `TASK_E_001` 用于不可达、zone 不合法、禁区导致无点可用。
- `TASK_E_002` 用于天然超载或超力矩。
- auto generation 不得把失败候选标记为 `skipped`。
- manual generation 默认也返回 startup blocking error；只有显式 `invalid_manual_task_policy=skip` 时才允许 `skipped`。

建议最大尝试次数来自 layout 的 `max_sampling_attempts` 或新增 task generation 参数；若使用 layout 参数，report 必须明确记录来源。

## 测试要求

建议测试文件：

```text
backend/app/tests/test_task_generation.py
```

必测场景：

- 同一 seed 两次生成的任务完全一致。
- 不同 seed 至少任务点或任务顺序不同。
- 每台塔吊生成 `num_tasks_per_crane` 个任务。
- task_id 稳定且不重复。
- pickup 来自 material zones。
- dropoff 来自 work zones。
- pickup/dropoff 落在 site boundary 内。
- load_type 满足 material/work zone 交集。
- `easy_task` 可生成基础可达任务。
- `overlap_task` 至少一个目标点靠近多塔 overlap 区域。
- `stress_task` 多塔 planned_start_s 接近且 deadline 更紧。
- manual mode 保留模板 task_id 并采样具体点。
- manual mode 在当前 schema 下按 deterministic assignment 选择可行 crane。
- 无可用 zone 时返回 `TASK_E_001`。
- 无 overlap region 时 `overlap_task/stress_task` 返回明确 report reason 或重采样。
- 所有生成任务 `status=pending`。

推荐命令：

```bash
pytest backend/app/tests/test_task_generation.py -v
```

## 验收标准

- 任务生成不依赖真实 LLM、controller 或 physics step。
- 所有任务可序列化，且包含 zone、load、priority、deadline 和 seed 追踪信息。
- 生成器不预设操作路线。
- 生成失败原因稳定、可测试、可写入 report。
