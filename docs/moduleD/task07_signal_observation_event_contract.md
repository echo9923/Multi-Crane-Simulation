# Task 07：地面信号提示、Observation 边界与任务事件合同

## 任务目标

定义模块 D 提供给 operator/LLM observation 的任务侧信息，以及模块 D 提交给事件系统的 task event payload。D 只提供当前任务、当前阶段、可解释提示和历史事件，不构造完整 prompt，不调用 LLM，也不暴露禁止信息。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.5.7`、`0.5.9`、`0.5.12`、`0.5.18`、`模块 D` 和 `模块 G` observation 边界。

## 任务范围

本任务实现：

- `TaskObservationContext` 读取侧合同。
- 当前任务目标摘要。
- deadline/priority/overtime 摘要。
- 地面信号提示生成。
- attach/release rejected history 摘要。
- task event payload 规范。
- idle 阶段 observation 隐私边界。

本任务不实现：

- 完整 LLM prompt 模板。
- provider 调用。
- risk hint 生成。
- 天气 observation。
- command log 落盘。
- event ID 分配和 JSONL 写入。

## 建议代码位置

```text
backend/app/sim/task_observation.py
backend/app/sim/task_events.py
backend/app/tests/test_task_observation_events.py
```

## TaskObservationContext

建议字段：

```text
schema_version: str
crane_id: str
time_s: float
has_active_task: bool
task_id: str | null
task_type: str | null
task_stage: str
priority: str | null
deadline_s: float | null
deadline_missed: bool
overtime_s: float
pickup: TaskPoint | null
dropoff: TaskPoint | null
current_target: TaskPoint | null
load_type: str | null
load_weight_t: float | null
load_size_m: list[float] | null
load_attached: bool
ground_signal_hint: str | null
recent_task_events: list[dict]
```

说明：

- `current_target` 根据 stage 指向 pickup、dropoff 或 recovery dropoff。
- `ground_signal_hint` 是局部对准提示，不是路径规划。
- `recent_task_events` 只包含已发生事件。

## 允许进入 observation 的任务信息

允许：

- 自己当前 active task 的 pickup/dropoff。
- 自己当前 `task_stage`。
- 自己当前 priority、deadline、deadline_missed、overtime。
- 自己当前 load_type、load_weight_t、load_size_m。
- attach/release 请求失败原因摘要。
- recovery_release 状态和恢复卸载目标。
- 已发生的任务阶段变化和任务结果摘要。

禁止：

- 邻塔完整任务目标。
- 邻塔任务队列。
- 自己下一任务是否存在、下一任务目标、下一任务 planned_start_s。
- 未来真实轨迹、future_min_distance、offline label。
- 任务生成器内部随机尝试记录。

邻塔当前 `task_stage` 是否可见由模块 G 的 observation visibility 规则控制；D 不主动暴露邻塔任务目标。

## idle observation

当 `task_stage=idle` 且无 active task：

```text
has_active_task = false
task_id = null
pickup = null
dropoff = null
current_target = null
ground_signal_hint = "当前无任务，请保持塔吊安全静止并观察现场。"
```

不得包含：

- 下一任务 ID。
- 下一任务开始时间。
- 下一任务 pickup/dropoff。
- 队列剩余数量。

如果操作员在 idle 阶段输出非 neutral 动作：

```text
emit idle_unnecessary_motion
```

该事件不默认终止 episode。

## 地面信号提示

提示目标：

- 帮助 LLM 完成局部对准。
- 模拟信号工/司索工的现场提示。
- 不提供全局路线规划。

输入：

- 当前 hook position。
- 当前 stage。
- 当前 target point。
- 阈值配置。

示例提示：

```text
吊钩在取货点东侧 0.6m、北侧 0.3m，高度偏高 1.2m，请小车和回转微调后缓慢下降。
```

提示规则：

- 只描述相对误差，不指挥完整路径。
- 数值应按 observation 精度控制进行四舍五入。
- 不能说“下一步必然安全”或“不会碰撞”。
- risk hint 由风险模块提供，不由 D 生成。

## 当前 target 规则

```text
move_to_pickup / align_pickup / lower_for_attach / attach_pending:
  current_target = pickup

lift_load:
  current_target = safe transport height over pickup

move_to_dropoff / align_dropoff / lower_for_release / release_pending:
  current_target = dropoff

recovery_release:
  current_target = recovery dropoff

idle:
  current_target = null
```

## task event types

模块 D 应能提交以下事件 payload：

```text
task_generated
task_started
task_stage_changed
attach_request_rejected
release_request_rejected
attach_pending_started
release_pending_started
attach_pending_cancelled
release_pending_cancelled
load_attached
load_released
deadline_missed
task_completed
task_failed
task_skipped
recovery_release_started
recovery_release_completed
recovery_release_failed
idle_unnecessary_motion
```

EventSink 可决定是否全部落盘；D 不负责去重策略，但 payload 必须稳定。

## 事件 payload 字段

最低字段：

```text
schema_version
event_type
time_s
frame_index
crane_id
task_id
task_type
task_status
task_stage
reason
details
```

推荐 details：

`attach_request_rejected`：

```text
xy_error_m
height_error_m
slew_speed_deg_s
trolley_speed_m_s
hoist_speed_m_s
load_attached
reason
```

`deadline_missed`：

```text
deadline_s
started_at_s
deadline_time_s
overtime_s
priority
```

`task_failed`：

```text
failure_reason
error_code
load_attached
recovery_task_id | null
```

`load_attached`：

```text
load_type
load_weight_t
load_size_m
pickup_zone_id
```

`load_released`：

```text
load_type
load_weight_t
dropoff_zone_id
```

## 与 recorder 的边界

D 提交事件 payload：

```text
TaskEventPayload
```

Recorder/EventSink 负责：

- 分配 event_id。
- 去重或 cooldown。
- 写入 `events.jsonl`。
- 写入 `tasks.parquet`。
- 汇总 episode summary。
- 前端点击跳转字段。

D 不直接打开文件。

## 测试要求

建议测试文件：

```text
backend/app/tests/test_task_observation_events.py
```

必测场景：

- active task observation 包含当前任务目标。
- idle observation 不包含下一任务信息。
- deadline_missed 和 overtime 进入 observation。
- recovery_release observation 明确不再追求原任务 deadline。
- ground signal 对 pickup 误差给出局部提示。
- ground signal 不包含全局路线。
- attach_request_rejected event 包含 reason 和误差。
- task_failed event 包含 error_code 和 recovery_task_id。
- event payload 可 JSON 序列化。
- D 不导入 LLM provider 或 recorder writer。

推荐命令：

```bash
pytest backend/app/tests/test_task_observation_events.py -v
```

## 验收标准

- operator 能获取完成当前任务所需的任务侧信息。
- idle 和邻塔任务隐私边界不被破坏。
- 任务事件足够 recorder、summary 和前端回放使用。
- D 保持为 observation/task event 提供者，不越界成为 prompt 或 recorder 模块。
