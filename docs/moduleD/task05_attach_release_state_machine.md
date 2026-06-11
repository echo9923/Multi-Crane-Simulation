# Task 05：任务阶段推进与挂载/卸载状态机

## 任务目标

实现运行时任务状态机，在 physics step 之后根据后验 `CraneState`、active task、`TaskActionSignal` 和计时器推进 `CraneState.task_stage`，并在挂载/卸载完成时更新载荷权威字段。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.5.7`、`0.6.2`、`0.7.7`、`0.7.8`、`模块 D.4-D.5` 和 `15.8 ISSUE-006`。

## 任务范围

本任务实现：

- active 普通任务的阶段推进。
- attach request 合法性判断。
- release request 合法性判断。
- attach/release pending 延迟。
- pending 期间条件漂出取消。
- 挂载完成时写入载荷字段。
- 卸载完成时清空载荷字段。
- `recovery_release` 阶段的 release 判定、pending 延迟和载荷清空。
- attach/release rejected 事件。

本任务不实现：

- 队列启动，归 Task 04。
- deadline/timeout/recovery task 创建和目标选择，归 Task 06。
- 控制目标生成。
- LLM 调用。
- 风险避让。

## 建议代码位置

```text
backend/app/sim/task_state_machine.py
backend/app/tests/test_task_state_machine.py
```

## 调用时机

按单帧生命周期：

```text
10. controller 将 ExecutedCommand 转成 ControlTarget
11. physics/kinematics step 到 state_{t+dt}
12. task state machine 基于 state_{t+dt} 更新阶段、挂载/卸载、任务事件
```

状态机必须使用 physics step 后的 `hook_position`、速度和载荷状态。

## 输入与输出

输入：

- active `Task`
- assigned `CraneConfig`
- post-physics `CraneState`
- `TaskActionSignal`
- 当前 `time_s`
- state machine config
- per-task runtime timers

输出：

- 更新后的 `Task`
- 更新后的 `CraneState` task/load 字段 patch
- `TaskRuntimeDiagnostic`
- 任务事件 payload

## 阶段推进规则

### move_to_pickup -> align_pickup

条件：

```text
xy_distance(hook, task.pickup) <= align_xy_threshold_m
```

动作：

```text
CraneState.task_stage = align_pickup
```

### align_pickup -> lower_for_attach

条件：

```text
xy_distance(hook, task.pickup) <= align_xy_threshold_m
hook_h_m > pickup.z + attach_height_threshold_m
```

动作：

```text
CraneState.task_stage = lower_for_attach
```

### lower_for_attach -> attach_pending

条件：

```text
TaskActionSignal.task_action == request_attach
xy_distance(hook, pickup) <= attach_xy_threshold_m
abs(hook_h_m - pickup.z) <= attach_height_threshold_m
axis speeds <= attach_speed_threshold
CraneState.load_attached == false
task.load_weight_t allowed at current hook radius
```

动作：

```text
CraneState.task_stage = attach_pending
pending_started_at_s = time_s
emit attach_pending_started
```

如果 `request_attach` 出现在错误阶段或条件不满足：

```text
拒绝请求
不改变 load_attached
保持当前阶段
emit attach_request_rejected
```

### attach_pending -> lift_load

条件：

```text
time_s - pending_started_at_s >= sampled_attach_delay_s
attach 条件仍满足
```

动作：

```text
CraneState.load_attached = true
CraneState.load_type = Task.load_type
CraneState.load_weight_t = Task.load_weight_t
CraneState.load_size_m = Task.load_size_m
CraneState.task_stage = lift_load
emit load_attached
```

如果 pending 期间条件漂出：

```text
CraneState.task_stage = lower_for_attach
pending_started_at_s = null
emit attach_pending_cancelled
```

### lift_load -> move_to_dropoff

条件：

```text
hook_h_m >= max(
  task.pickup.z + lift_clearance_m,
  safe_transport_height_m
)
```

动作：

```text
CraneState.task_stage = move_to_dropoff
```

### move_to_dropoff -> align_dropoff

条件：

```text
xy_distance(hook, task.dropoff) <= align_xy_threshold_m
```

动作：

```text
CraneState.task_stage = align_dropoff
```

### align_dropoff -> lower_for_release

条件：

```text
xy_distance(hook, task.dropoff) <= align_xy_threshold_m
hook_h_m > dropoff.z + release_height_threshold_m
CraneState.load_attached == true
```

动作：

```text
CraneState.task_stage = lower_for_release
```

### lower_for_release -> release_pending

条件：

```text
TaskActionSignal.task_action == request_release
xy_distance(hook, dropoff) <= release_xy_threshold_m
abs(hook_h_m - dropoff.z) <= release_height_threshold_m
axis speeds <= release_speed_threshold
CraneState.load_attached == true
```

动作：

```text
CraneState.task_stage = release_pending
pending_started_at_s = time_s
emit release_pending_started
```

如果 `request_release` 出现在错误阶段或条件不满足：

```text
拒绝请求
不改变 load_attached
保持当前阶段
emit release_request_rejected
```

### release_pending -> completed

条件：

```text
time_s - pending_started_at_s >= sampled_release_delay_s
release 条件仍满足
```

动作：

```text
CraneState.load_attached = false
CraneState.load_type = null
CraneState.load_weight_t = 0.0
CraneState.load_size_m = null
CraneState.task_stage = idle
CraneState.task_id = null
Task.status = completed
Task.completed_at_s = time_s
emit load_released
emit task_completed
```

如果 pending 期间条件漂出：

```text
CraneState.task_stage = lower_for_release
pending_started_at_s = null
emit release_pending_cancelled
```

### recovery_release

`recovery_release` 的创建、目标选择和 timeout 归 Task 06；一旦 Task 06 创建 active `RecoveryTask` 并把 `CraneState.task_stage` 置为 `recovery_release`，本任务负责执行卸载判定。

进入 recovery release pending 的条件：

```text
CraneState.task_stage == recovery_release
Task.task_type == recovery_release
TaskActionSignal.task_action == request_release
xy_distance(hook, recovery_dropoff) <= release_xy_threshold_m
abs(hook_h_m - recovery_dropoff.z) <= release_height_threshold_m
axis speeds <= release_speed_threshold
CraneState.load_attached == true
```

动作：

```text
pending_started_at_s = time_s
emit release_pending_started
```

完成条件：

```text
time_s - pending_started_at_s >= sampled_release_delay_s
release 条件仍满足
```

完成动作：

```text
CraneState.load_attached = false
CraneState.load_type = null
CraneState.load_weight_t = 0.0
CraneState.load_size_m = null
CraneState.task_id = null
CraneState.task_stage = idle
RecoveryTask.status = completed
RecoveryTask.completed_at_s = time_s
emit load_released
emit recovery_release_completed
```

如果 recovery pending 期间条件漂出：

```text
pending_started_at_s = null
CraneState.task_stage = recovery_release
emit release_pending_cancelled
```

## 速度阈值

速度阈值按轴检查：

```text
abs(theta_dot_rad_s) <= deg_to_rad(slew_deg_s)
abs(trolley_v_m_s) <= trolley_m_s
abs(hoist_v_m_s) <= hoist_m_s
```

不得只检查单一合速度。

## 载重再检查

进入 `attach_pending` 前必须再次检查当前半径处 capacity：

```text
capacity_at_radius_t(current_hook_radius) >= task.load_weight_t
```

该检查是 runtime 防御，不应替代 Task 03 的启动前校验。若失败：

- 拒绝 attach。
- 记录 reason `runtime_over_capacity`.
- 不改变 `Task.status`。

基础机械安全层后续仍可做更强的限载/力矩保护。

## 错误阶段请求

必须拒绝并记录：

- idle 时 request_attach/request_release。
- move_to_pickup 时 request_release。
- move_to_dropoff 前 request_release。
- 已挂载时 request_attach。
- 未挂载时 request_release。
- 距离/高度/速度条件不满足时 request_attach/request_release。

这些拒绝不默认终止任务或 episode。

## 测试要求

建议测试文件：

```text
backend/app/tests/test_task_state_machine.py
```

必测场景：

- hook 到 pickup 附近后 `move_to_pickup -> align_pickup`。
- 对准且仍在上方时 `align_pickup -> lower_for_attach`。
- 条件满足且 request_attach 后进入 `attach_pending`。
- attach delay 结束且条件仍满足后 `load_attached=true`。
- attach pending 条件漂出后取消并回到 `lower_for_attach`。
- 错误阶段 request_attach 被拒绝且不改变载荷。
- lift 到安全高度后进入 `move_to_dropoff`。
- hook 到 dropoff 附近后进入 `align_dropoff`。
- 条件满足且 request_release 后进入 `release_pending`。
- release delay 结束且条件仍满足后任务 completed。
- release pending 条件漂出后取消并回到 `lower_for_release`。
- recovery_release 条件满足且 request_release 后可完成恢复卸载。
- recovery_release pending 漂出阈值后保持 `recovery_release`。
- 未挂载 request_release 被拒绝。
- 速度超过阈值时 attach/release 被拒绝。
- runtime over capacity 时 attach 被拒绝。

推荐命令：

```bash
pytest backend/app/tests/test_task_state_machine.py -v
```

## 验收标准

- 任务阶段只能由 D 推进。
- LLM 只能通过 `task_action` 请求影响挂载/卸载。
- pending 延迟和条件复检行为确定。
- 挂载/卸载完成瞬间正确更新载荷字段。
- 所有拒绝和取消都有事件或 diagnostic。
