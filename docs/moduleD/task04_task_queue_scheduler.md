# Task 04：每塔独立任务队列与启动调度

## 任务目标

实现每台塔吊独立任务队列的 runtime scheduler。scheduler 负责在正确时间激活 pending task，并在任务完成或失败后按 `planned_start_s` 或 `inter_task_delay_s` 等待下一任务。它不推进 attach/release 阶段细节。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.5.6`、`0.6.2`、`0.7.8`、`模块 D.4` 和 `模块 D.7`。

## 任务范围

本任务实现：

- `TaskQueue` 初始化。
- `simultaneous`、`staggered`、`scheduled` 三种启动策略的运行时解释。
- pending task 激活。
- active task 完成/失败后的下一任务等待。
- idle 阶段的 next-task 隐私边界。
- all ordinary tasks done 的查询接口。

本任务不实现：

- 任务生成采样。
- attach/release 状态机。
- deadline missed 判断。
- LLM observation 构造。
- episode terminal status。

## 建议代码位置

```text
backend/app/sim/task_queue.py
backend/app/tests/test_task_queue_scheduler.py
```

## 调用时机

按总方案单帧生命周期，scheduler 应在每帧早期运行：

```text
1. update_weather(t)
2. task scheduler 激活到达 planned_start_s / inter_task_delay 的任务
3. 判断哪些 crane 到达 LLM/rule 决策时刻
4-11. observation、operator、safety、controller 和 physics step
12. task state machine 基于 state_{t+dt} 更新阶段、挂载/卸载、任务事件
```

因此本任务只在 physics step 前激活任务；Task 05 在 physics step 后推进阶段。

## 输入与输出

输入：

- `TaskQueue[]`
- 当前 `time_s`
- 每台塔吊当前 `CraneState.task_stage`
- 每台塔吊 `load_attached`

输出：

- 更新后的 `TaskQueue[]`
- 更新后的 `Task.status`
- 需要写入 `CraneState.task_id/task_stage` 的 patch
- `task_started` 事件 payload

## 激活规则

对每台塔吊独立执行：

```text
如果 blocked_by_recovery=true:
  不激活普通任务。

如果已有 active_task_id:
  不激活新任务。

如果 next_task_index 超出队列:
  保持 idle。

如果 current time_s < queue.ready_after_s:
  保持 idle。

取 next pending task:
  如果 task.planned_start_s != null 且 time_s < planned_start_s:
    保持 idle。
  否则:
    task.status = active
    task.started_at_s = time_s
    queue.active_task_id = task.task_id
    queue.next_task_index += 1
    CraneState.task_id = task.task_id
    CraneState.task_stage = move_to_pickup
    emit task_started
```

`planned_start_s` 是绝对 episode 时间。如果当前时间已经超过 `planned_start_s`，任务应立即开始，不再等待。

## 完成后等待规则

Task 05/06 把 active task 置为 completed 或 failed 后，queue scheduler 应清理 active slot：

```text
queue.active_task_id = null
queue.last_completed_task_id = task_id, if completed
queue.ready_after_s = time_s + sampled_inter_task_delay_s, if next task has no planned_start_s
CraneState.task_id = null
CraneState.task_stage = idle, unless recovery_release is active
```

如果下一任务有 `planned_start_s`，`ready_after_s` 仍可记录 inter-task delay，但激活时必须同时满足：

```text
time_s >= ready_after_s
time_s >= planned_start_s
```

## simultaneous

生成阶段推荐：

```text
first task planned_start_s = 0.0
later tasks planned_start_s = null
```

运行时语义：

- episode 开始时所有塔吊第一个任务可立即激活。
- 后续任务按 inter-task delay。

## staggered

生成阶段推荐：

```text
first task planned_start_s = sampled initial_start_jitter_s
later tasks planned_start_s = null
```

运行时语义：

- 第一批任务错开启动。
- 后续任务按 inter-task delay。

## scheduled

生成阶段或 manual template 可提供显式 `planned_start_s`。

运行时语义：

- 未到 planned_start 不激活。
- 当前任务完成太晚时，若下一任务 planned_start 已过，则在 inter-task delay 满足后立即激活。

## idle 边界

idle 阶段：

- `CraneState.task_stage = idle`
- `CraneState.task_id = null`
- 可以按 LLM 决策频率调用 operator。
- observation 只能说明“当前无 active task，应保持安全静止并观察现场”。
- 不得提前暴露下一任务是否存在、下一任务开始时间、下一任务目标。
- 如果 operator 在 idle 阶段输出非 neutral 动作，应记录 `idle_unnecessary_motion`，但不静默改写命令。

idle 事件可以由 D 或 J/G 记录；如果由 D 记录，D 只读取 `TaskActionSignal.motion_is_non_neutral`。

## recovery block

只要当前塔吊仍带载且处于 `recovery_release`：

```text
queue.blocked_by_recovery = true
```

普通任务不得激活。恢复结束后：

```text
load_attached=false
queue.blocked_by_recovery=false
CraneState.task_stage=idle
```

## all tasks done 查询

提供只读查询：

```text
all_ordinary_tasks_terminal(queues) -> bool
```

返回 true 条件：

- 所有普通任务 `status in {completed, failed, skipped}`。
- 没有 active 普通任务。
- 没有 active recovery task。
- 没有塔吊 `blocked_by_recovery`。

该函数不决定 episode status；调度器可结合 collision、timeout、cooldown 判断 `completed`。

## 测试要求

建议测试文件：

```text
backend/app/tests/test_task_queue_scheduler.py
```

必测场景：

- simultaneous 第一任务在 `time_s=0` 激活。
- staggered 第一任务未到 planned_start 前保持 idle。
- scheduled planned_start 已过时可立即激活。
- 已有 active task 时不激活下一任务。
- completed task 后按 inter_task_delay 等待。
- 下一任务有 planned_start 时必须同时满足 delay 和 planned_start。
- `blocked_by_recovery=true` 时不激活普通任务。
- idle 状态不暴露下一任务信息的 observation context 只包含 active task null。
- all ordinary tasks terminal 查询正确。
- 不硬编码塔吊数量。

推荐命令：

```bash
pytest backend/app/tests/test_task_queue_scheduler.py -v
```

## 验收标准

- 每台塔吊独立队列可确定性启动。
- 队列状态和 `CraneState.task_stage` 保持一致。
- idle 隐私边界清晰。
- scheduler 不越界推进 attach/release 或物理状态。
