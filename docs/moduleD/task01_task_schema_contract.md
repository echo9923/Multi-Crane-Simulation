# Task 01：任务对象、状态枚举与配置合同

## 任务目标

定义模块 D 的运行时领域对象，使任务生成器、队列 scheduler、状态机、recorder 和前端都使用同一套 `Task` 合同。该任务只定义对象和配置缺口，不实现采样算法，也不推进状态机。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.5.6`、`0.5.7`、`0.6.2`、`0.6.3`、`模块 D.2-D.4` 和 `15.3`。

## 任务范围

本任务实现或预留：

- `TaskStatus`
- `TaskStage`
- `TaskType` 的运行时扩展说明
- `TaskPoint`
- `Task`
- `TaskQueue`
- `TaskGenerationReport`
- `TaskRuntimeDiagnostic`
- `TaskActionSignal`
- 任务事件 payload 的基础字段
- D 所需但当前配置 schema 尚未覆盖的阈值和 recovery 配置合同

本任务不实现：

- 任务点采样。
- 任务可行性校验。
- 队列启动。
- attach/release 状态机。
- recorder 文件写入。

## 建议代码位置

```text
backend/app/schemas/task.py
backend/app/sim/tasks.py
backend/app/tests/test_task_schema.py
```

若需要补齐配置 schema，修改位置应为：

```text
backend/app/schemas/config.py
backend/app/tests/test_config_schema.py
```

配置 schema 的 owner 仍是模块 A；模块 D 只是提出并消费这些字段。

## 核心枚举

`TaskStatus`：

```text
pending
active
completed
failed
skipped
```

`TaskStage`：

```text
idle
move_to_pickup
align_pickup
lower_for_attach
attach_pending
lift_load
move_to_dropoff
align_dropoff
lower_for_release
release_pending
recovery_release
```

普通生成任务类型：

```text
easy_task
overlap_task
stress_task
```

运行时内部任务类型：

```text
recovery_release
```

边界规则：

- `recovery_release` 可作为 runtime `Task.task_type`，但不得进入 `tasks.task_type_distribution`。
- `pending` 只属于 `Task.status`，不得作为 `CraneState.task_stage`。
- `idle` 只属于塔吊阶段，表示当前无 active 普通任务或等待下一任务启动。
- M1 默认不产生 `skipped`；该状态只作为未来 manual task 容错策略预留。

## TaskPoint

建议字段：

```text
schema_version: str
x: float
y: float
z: float
zone_id: str
zone_type: "material" | "work" | "recovery"
```

说明：

- 坐标使用 ENU，单位 m。
- `pickup.zone_type` 必须是 `material`。
- `dropoff.zone_type` 必须是 `work`，recovery 任务可使用 `recovery`。
- z 是目标点世界高度，不是相对楼层高度。

## Task

最低字段：

```text
schema_version: str
task_id: str
crane_id: str
task_type: str
pickup: TaskPoint
dropoff: TaskPoint
pickup_zone_id: str
dropoff_zone_id: str
planned_start_s: float | null
load_type: str
load_weight_t: float
load_size_m: list[float]
priority: "low" | "medium" | "high"
deadline_s: float | null
deadline_missed: bool
overtime_s: float
status: TaskStatus
started_at_s: float | null
completed_at_s: float | null
failed_at_s: float | null
failure_reason: str | null
source_failed_task_id: str | null
generation_seed: int
generation_attempt: int
```

字段解释：

- `planned_start_s` 是 episode 绝对时间。
- `deadline_s` 是从任务实际开始时刻起算的建议完成时长。
- 运行时可派生 `deadline_time_s = started_at_s + deadline_s`，但不要求写回 config。
- `deadline_missed=true` 不改变 `status`。
- `source_failed_task_id` 仅用于 `recovery_release`。
- `generation_attempt` 用于追溯任务生成时的重采样次数。

## TaskQueue

最低字段：

```text
schema_version: str
crane_id: str
tasks: list[Task]
active_task_id: str | null
next_task_index: int
last_completed_task_id: str | null
ready_after_s: float
blocked_by_recovery: bool
```

规则：

- 每台塔吊一个队列。
- 队列顺序由任务生成器确定，运行时不跨塔抢任务。
- `blocked_by_recovery=true` 时不得激活普通下一任务。

## TaskActionSignal

模块 D 不拥有完整 `ExecutedCommand`，只需要读取任务动作摘要：

```text
schema_version: str
crane_id: str
command_id: str | null
time_s: float
task_action: "none" | "request_attach" | "request_release"
motion_is_non_neutral: bool
```

读取规则：

- `task_action=none` 不触发 attach/release。
- `motion_is_non_neutral=true` 且当前 `task_stage=idle` 时，D 或调度器应记录 `idle_unnecessary_motion`。
- D 不读取 LLM reason、prompt、raw response、operator profile 或完整 joystick 内容。

## 配置合同补齐

当前 `TaskStateMachineConfig` 已包含大部分字段，但总方案要求 attach/release speed threshold。模块 D 实现前必须补齐：

```yaml
tasks:
  state_machine:
    attach_speed_threshold:
      slew_deg_s: 0.3
      trolley_m_s: 0.08
      hoist_m_s: 0.05
    release_speed_threshold:
      slew_deg_s: 0.3
      trolley_m_s: 0.08
      hoist_m_s: 0.05
    no_progress_xy_epsilon_m: 0.25
```

必须新增恢复配置，或在 resolved task generation 中写入等价默认值：

```yaml
tasks:
  recovery:
    enabled: true
    policy: "attempt_safe_release"
    emergency_drop_zones: []
```

如果 M1 初版不扩展 YAML 输入，也必须在 `ResolvedConfig.tasks.generation` 中写入这些默认值，使运行可复现。后续 Task 05/06 不得依赖代码内部隐式常量。

Task 01 的配置验收必须覆盖：

- `attach_speed_threshold.slew_deg_s/trolley_m_s/hoist_m_s` 可解析且为正数。
- `release_speed_threshold.slew_deg_s/trolley_m_s/hoist_m_s` 可解析且为正数。
- `no_progress_xy_epsilon_m` 可解析且为正数。
- `recovery.enabled` 可解析。
- `recovery.policy` 只允许 `attempt_safe_release` 或 `terminate_episode`。
- `recovery.emergency_drop_zones` 可解析为空列表或 zone id 列表。
- `recovery_release` 不允许进入 `TaskGenerationConfig.task_type_distribution`。

## 任务事件基础字段

所有 D 产生的事件 payload 至少包含：

```text
schema_version
event_type
time_s
frame_index | null
crane_id
task_id | null
task_stage | null
task_status | null
reason | null
details
```

事件 ID、去重、落盘由 EventSink/recorder 负责，D 只提交 payload。

## 边界规则

- `Task` 是任务语义权威；`CraneState` 只保存当前执行引用和载荷字段。
- `Task.status` 只能由模块 D 推进。
- `CraneState.task_stage` 只能由模块 D 推进，初始化时模块 C 可设置为 `idle`。
- `load_attached/load_type/load_weight_t/load_size_m` 只能在 attach/release 完成或恢复卸载完成时由模块 D 修改。
- 模块 C 可以根据 `load_attached` 派生 `load_position`，但不决定挂载是否成功。

## 测试要求

建议测试文件：

```text
backend/app/tests/test_task_schema.py
```

必测场景：

- `Task.status=pending` 可创建。
- `CraneState.task_stage=idle` 可作为初始阶段。
- `Task.status=idle` 被拒绝。
- `TaskStage.pending` 不存在。
- `recovery_release` 可作为 runtime task type。
- `recovery_release` 不允许出现在 generation distribution。
- 默认策略下不会生成 `status=skipped` 的任务。
- `deadline_s` 为正数或 null。
- `load_size_m` 必须是 3 个正数。
- `TaskActionSignal.task_action` 只接受 `none/request_attach/request_release`。
- attach/release speed threshold 和 recovery policy 配置可被 schema 接收。

推荐命令：

```bash
pytest backend/app/tests/test_task_schema.py -v
pytest backend/app/tests/test_config_schema.py -v
```

## 验收标准

- 后续任务能只依赖 `Task` 和 `TaskQueue` 合同实现。
- 状态枚举清楚地区分任务队列状态和塔吊执行阶段。
- 配置缺口被补齐到 schema，或至少写入 resolved 默认值且有测试覆盖。
- 对象可 JSON 序列化，能被 recorder 和前端复用。
