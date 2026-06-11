# Task 06：deadline、timeout、任务失败与 recovery_release

## 任务目标

实现任务效率记录和失败恢复规则，确保 deadline missed 不被误判为任务失败，同时 attach/release/no-progress timeout 能正确失败当前任务；release 失败且仍带载时必须进入 `recovery_release`。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.5.6`、`0.6.3`、`0.7.7`、`0.8.6`、`模块 D.6-D.7` 和错误矩阵。

## 任务范围

本任务实现：

- deadline missed 判断。
- overtime_s 更新。
- attach_stage_timeout。
- release_stage_timeout。
- task_no_progress_timeout。
- task failed 后的 queue/state 处理。
- `recovery_release` 创建、目标选择、timeout 和 blocked failure。
- `TASK_E_101`、`TASK_E_102`、`TASK_E_103`、`TASK_E_104`、`TASK_E_105`、`TASK_W_201` 映射。

本任务不实现：

- 普通阶段推进和 recovery release 的具体 release 判定，归 Task 05。
- episode status 最终写入，归模块 J。
- recorder 落盘。
- 自动清空载荷。

## 建议代码位置

```text
backend/app/sim/task_failure.py
backend/app/sim/task_recovery.py
backend/app/tests/test_task_failure_recovery.py
```

## deadline 规则

`deadline_s` 是从任务实际开始时刻起算的建议完成时长：

```text
deadline_time_s = Task.started_at_s + Task.deadline_s
```

如果 `deadline_s=null` 或 `deadline_policy.enabled=false`，跳过 deadline missed 判断，`deadline_missed=false` 且 `overtime_s=0.0`。

当：

```text
time_s > deadline_time_s
Task.deadline_missed == false
Task.status == active
```

执行：

```text
Task.deadline_missed = true
Task.overtime_s = time_s - deadline_time_s
emit deadline_missed
```

之后每帧或每次任务更新：

```text
Task.overtime_s = max(0, time_s - deadline_time_s)
```

边界：

- `deadline_missed` 不改变 `Task.status`。
- `deadline_missed` 不改变 `CraneState.task_stage`。
- `deadline_missed` 不终止 episode。
- `deadline_policy.deadline_miss_is_task_failure` 当前应保持 false；若配置为 true，必须在文档和数据集 metadata 中显式标记为非默认实验。

## attach_stage_timeout

计时范围：

```text
move_to_pickup
align_pickup
lower_for_attach
attach_pending
```

推荐起点：

```text
Task.started_at_s
```

当超过 `attach_stage_timeout_s` 且 `load_attached=false`：

```text
Task.status = failed
Task.failed_at_s = time_s
Task.failure_reason = failed_attach_timeout
CraneState.task_id = null
CraneState.task_stage = idle
emit task_failed(error_code=TASK_E_101)
```

如果 attach timeout 时 `load_attached=true`：

```text
这是状态机不一致
emit diagnostic
return episode failure request failed_invalid_state
```

最终 episode status 由模块 J 写入。

## release_stage_timeout

计时范围：

```text
move_to_dropoff
align_dropoff
lower_for_release
release_pending
```

推荐起点：

```text
进入 move_to_dropoff 的时间
```

当超过 `release_stage_timeout_s` 且 `load_attached=false`：

```text
Task.status = failed
Task.failed_at_s = time_s
Task.failure_reason = failed_release_timeout
CraneState.task_id = null
CraneState.task_stage = idle
emit task_failed(error_code=TASK_E_102)
```

如果 release timeout 时 `load_attached=true`：

```text
Task.status = failed
Task.failed_at_s = time_s
Task.failure_reason = failed_release_timeout
CraneState.task_stage = recovery_release
queue.blocked_by_recovery = true
create RecoveryTask
emit task_failed(error_code=TASK_E_103)
emit recovery_release_started
```

普通下一任务不得启动。

如果 release timeout 时 `load_attached=false` 但任务尚未 completed：

- 若最近一帧已经执行 release 完成但 task status 未同步，修正为 completed 并记录 diagnostic。
- 否则返回 failed_invalid_state 请求，由模块 J 处理。

## no-progress timeout

`task_no_progress_timeout_s` 用于避免任务长期卡住但没有进入 attach/release timeout。

进展事件包括：

- `Task.status` 从 pending 变 active。
- `CraneState.task_stage` 发生合法阶段转移。
- attach/release pending 开始、取消或完成。
- 到当前阶段目标点的水平距离相比上一次 progress checkpoint 减少至少 `no_progress_xy_epsilon_m`。
- hook 高度误差相比上一次 progress checkpoint 减少至少 `no_progress_xy_epsilon_m`，仅在 lower 阶段使用。

当：

```text
time_s - last_progress_at_s > task_no_progress_timeout_s
```

处理：

- 未带载：当前任务 failed，进入 idle 或等待下一任务。
- 已带载：当前任务 failed，进入 `recovery_release`。

failure reason：

```text
failed_no_progress_timeout
```

错误码可复用 `TASK_E_101` 或 `TASK_E_103`，但 event reason 必须写明 no-progress。

## recovery_release 目标选择

只要 `load_attached=true`，塔吊不得直接开始普通下一任务。恢复目标选择顺序：

```text
1. 当前任务 dropoff 点，如果仍可达、未进入 hard forbidden zone，且力矩允许。
2. 当前 load_type 可接受的最近 work zone 安全点。
3. 当前 load_type 可接受的最近 material zone 安全点。
4. 配置中的 emergency_drop_zone。
5. 若以上都不存在，发出 failed_recovery_blocked 请求。
```

M1 初版如果尚未实现 safe_unload_zones，可至少实现第 1 条，并在无可用目标时返回 `TASK_E_105`。

## RecoveryTask

创建规则：

```text
task_id = R_<crane_id>_<source_failed_task_id>
task_type = recovery_release
status = active
source_failed_task_id = failed_task.task_id
pickup = current hook/load position
dropoff = selected recovery target
priority = high
deadline_s = null
deadline_missed = false
```

恢复任务：

- 不计入普通任务完成率。
- 必须计入 recovery 成功率。
- 必须写入 tasks recorder 输入。
- observation 必须明确“当前处于恢复卸载，不再追求原任务 deadline”。

## recovery_release 完成

恢复卸载的具体 release 判定、pending 延迟、条件漂出取消和载荷清空由 Task 05 执行。Task 06 只消费完成结果，解除队列 block：

```text
RecoveryTask.status == completed
CraneState.load_attached == false
```

Task 06 后处理：

```text
queue.blocked_by_recovery = false
```

之后才能启动普通下一任务。

## recovery_release 失败

当超过 `recovery_release_timeout_s`：

```text
RecoveryTask.status = failed
RecoveryTask.failure_reason = failed_recovery_timeout
emit task_failed(error_code=TASK_E_104)
return episode failure request failed_recovery_timeout
```

当找不到恢复目标：

```text
emit task_failed(error_code=TASK_E_105)
return episode failure request failed_recovery_blocked
```

模块 D 只返回 failure request；最终 episode status 由模块 J 写入。

## 禁止自动清空载荷

默认不得执行：

```text
load_attached=false
load_weight_t=0
```

来绕过恢复流程。

如果调试模式新增 `auto_clear_load_on_task_failure=true`：

- 必须默认关闭。
- 必须写入 summary/metadata。
- 不得用于研究数据默认生成。

## 测试要求

建议测试文件：

```text
backend/app/tests/test_task_failure_recovery.py
```

必测场景：

- deadline 超时只设置 `deadline_missed=true`，任务仍 active。
- deadline overtime_s 随时间更新。
- attach timeout 且未带载时任务 failed、阶段 idle。
- attach timeout 但已带载时请求 failed_invalid_state。
- release timeout 且未带载时任务 failed、episode 继续。
- release timeout 且仍带载时创建 recovery task。
- recovery active 时普通下一任务不能启动。
- recovery release 成功由 Task 05 清空载荷，Task 06 解除 block。
- recovery timeout 返回 `TASK_E_104`。
- 无 recovery target 返回 `TASK_E_105`。
- no-progress timeout 未带载时失败当前任务。
- no-progress timeout 已带载时进入 recovery_release。
- 任何失败路径都不静默清空载荷。

推荐命令：

```bash
pytest backend/app/tests/test_task_failure_recovery.py -v
```

## 验收标准

- deadline 和 timeout 的语义完全分离。
- release 失败带载时严格进入 recovery_release。
- recovery 任务可序列化、可记录、可被 observation 识别。
- 模块 D 不直接写 episode terminal status，只返回结构化 failure request。
