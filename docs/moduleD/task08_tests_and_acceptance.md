# Task 08：模块 D 测试清单与验收标准

## 任务目标

定义模块 D 的单元测试、合同测试、集成测试和验收退出条件，确保任务生成、队列启动、状态机、deadline、失败恢复和事件接口都可复现、可测试、边界清晰。

权威来源：`群塔LLM仿真系统开发方案_v0.4_完整版.md` 中 `0.5.6`、`0.5.7`、`0.7.5`、`0.7.7`、`0.7.8`、`0.8.6`、`模块 D.7`、`15.3` 和 `15.8 ISSUE-006`。

## 任务范围

本任务定义：

- schema/object 测试。
- 任务生成测试。
- 可行性校验测试。
- 队列 scheduler 测试。
- attach/release 状态机测试。
- deadline/failure/recovery 测试。
- observation/event 合同测试。
- 模块边界回归测试。
- M1 验收标准。

本任务不要求实现：

- 真实 LLM provider 集成。
- 完整调度器。
- 风险模块。
- recorder Parquet/JSONL writer。
- 前端回放。

## 建议测试文件

```text
backend/app/tests/test_task_schema.py
backend/app/tests/test_task_generation.py
backend/app/tests/test_task_feasibility.py
backend/app/tests/test_task_queue_scheduler.py
backend/app/tests/test_task_state_machine.py
backend/app/tests/test_task_failure_recovery.py
backend/app/tests/test_task_observation_events.py
backend/app/tests/test_moduleD_acceptance.py
```

## 推荐测试命令

开发中按任务运行：

```bash
pytest backend/app/tests/test_task_schema.py -v
pytest backend/app/tests/test_task_generation.py -v
pytest backend/app/tests/test_task_feasibility.py -v
pytest backend/app/tests/test_task_queue_scheduler.py -v
pytest backend/app/tests/test_task_state_machine.py -v
pytest backend/app/tests/test_task_failure_recovery.py -v
pytest backend/app/tests/test_task_observation_events.py -v
```

模块 D 完整验收：

```bash
pytest backend/app/tests/test_task_schema.py \
       backend/app/tests/test_task_generation.py \
       backend/app/tests/test_task_feasibility.py \
       backend/app/tests/test_task_queue_scheduler.py \
       backend/app/tests/test_task_state_machine.py \
       backend/app/tests/test_task_failure_recovery.py \
       backend/app/tests/test_task_observation_events.py \
       backend/app/tests/test_moduleD_acceptance.py -v
```

回归邻近模块：

```bash
pytest backend/app/tests/test_moduleB_acceptance.py \
       backend/app/tests/test_layout_reachability.py \
       backend/app/tests/test_moduleC_acceptance.py -v
```

## schema/object 验收

必须通过：

- `Task.status` 只接受 `pending/active/completed/failed/skipped`。
- `TaskStage` 只接受 D 规定的阶段。
- `pending` 不可作为 `TaskStage`。
- `idle` 不可作为 `TaskStatus`。
- `Task` 可 JSON 序列化。
- `TaskQueue` 可 JSON 序列化。
- `TaskActionSignal` 只暴露 D 需要的字段。
- `recovery_release` 是 runtime-only task type，不进入 generation distribution。
- 默认策略下不会生成 `status=skipped` 的任务。
- attach/release speed threshold 配置可解析并写入 resolved task generation。
- recovery policy 配置可解析并写入 resolved task generation。

## 任务生成验收

必须通过：

- 同一 seed 完全确定。
- 不同 seed 产生可观测差异。
- N 台塔吊都生成独立队列。
- 每台塔吊任务数量等于 `num_tasks_per_crane`。
- 任务 ID 不重复。
- pickup 来自 material zones。
- dropoff 来自 work zones。
- pickup/dropoff 落在 site boundary 内。
- load_type 来自场景 load types，并满足 zone 支持规则。
- `easy_task`、`overlap_task`、`stress_task` 都能生成。
- `stress_task` 通过目标点和 planned_start/deadline 制造压力，但不预设路线。
- `overlap_task/stress_task` 使用 D 派生的 `TaskOverlapRegion`，没有 overlap region 时有明确 report reason。
- manual task 在当前 schema 下按 deterministic assignment 分配给可行 crane。
- 生成失败返回稳定 `TASK_E_001` 或 `TASK_E_002`。

## 可行性验收

必须通过：

- 每个进入 episode 的 task 对 assigned crane 可达。
- 每个进入 episode 的 task 都在 site boundary 内。
- pickup/dropoff 不在 forbidden zone。
- load_weight_t 在 pickup/dropoff 半径处满足 capacity。
- 校验使用 `capacity_at_radius_t`。
- 不可达映射 `TASK_E_001`。
- 天然超载/超力矩映射 `TASK_E_002`。
- B reachability precheck 不能替代 D task-level 校验。

## 队列 scheduler 验收

必须通过：

- simultaneous 可在 episode 开始时激活第一任务。
- staggered 会等待 first task planned_start。
- scheduled 尊重显式 planned_start。
- active task 未结束前不启动下一任务。
- completed/failed 后按 inter_task_delay 等待。
- recovery block 时不启动普通任务。
- idle 不向 observation 暴露下一任务。
- 支持 N 台塔吊。

## 状态机验收

必须通过：

- `move_to_pickup -> align_pickup -> lower_for_attach` 按几何条件推进。
- 满足条件并 request_attach 才进入 `attach_pending`。
- attach delay 结束且条件仍满足才设置 `load_attached=true`。
- attach pending 漂出阈值会取消。
- 错误阶段 request_attach 被拒绝。
- lift 到安全高度后进入 dropoff 阶段。
- 满足条件并 request_release 才进入 `release_pending`。
- release delay 结束且条件仍满足才完成任务。
- release pending 漂出阈值会取消。
- 错误阶段 request_release 被拒绝。
- 挂载/卸载完成瞬间正确更新载荷字段。

## deadline、失败和恢复验收

必须通过：

- deadline missed 只记录 warning/event，不使任务 failed。
- overtime_s 正确更新。
- attach timeout 未带载时当前任务 failed，episode 默认继续。
- release timeout 未带载时当前任务 failed，episode 默认继续。
- release timeout 仍带载时进入 recovery_release。
- recovery_release 未完成前不启动普通下一任务。
- recovery 完成时由 Task 05 的 release 判定清空载荷并回到 idle，Task 06 解除 recovery block。
- recovery timeout 返回结构化 episode failure request。
- 任何默认路径都不自动清空载荷绕过恢复。

## observation/event 验收

必须通过：

- active task observation 包含当前任务阶段、目标、priority、deadline。
- idle observation 不包含下一任务信息。
- recovery observation 明确当前是恢复卸载。
- 地面信号提示只提供局部对准信息。
- task events 可 JSON 序列化。
- task_failed 事件包含 error_code、failure_reason、load_attached。
- attach/release rejected 事件包含拒绝原因。
- deadline_missed 事件包含 deadline_time_s 和 overtime_s。

## 模块边界回归

必须通过静态或单元测试确认：

- 模块 D 不调用真实 LLM provider。
- 模块 D 不导入 recorder writer。
- 模块 D 不计算 risk label、near-miss 或 collision。
- 模块 D 不生成 `ControlTarget`。
- 模块 D 不修改 `theta_rad`、`trolley_r_m`、`hook_h_m` 等运动字段。
- 模块 D 不生成或修改 `CraneConfig`。
- 模块 D 不直接写 episode terminal status，只返回 failure request 或事件。

## M1 验收场景

建议构造一个 3 塔 demo fixture：

```text
3 cranes
至少 2 个 material zones
至少 2 个 work zones
至少 2 个 load types
每台塔吊至少 3 个任务
task_type_distribution 覆盖 easy/overlap/stress
queue_policy 覆盖 staggered
```

使用 fake operator 或规则司机执行 easy_task：

- easy_task 完成率 >= 80%。
- overlap/stress 不要求完成率，但必须生成合法任务和事件。
- 任务失败不默认终止 episode。
- release 失败带载时必须触发 recovery_release。

## 完成定义

模块 D 完成后应满足：

1. 文档中所有 Task 01-07 的测试均通过。
2. `test_moduleD_acceptance.py` 通过。
3. 模块 A/B/C 的相邻合同测试仍通过。
4. 生成任务、状态机事件和 runtime task/load 字段可被 recorder 消费。
5. 没有把 LLM、controller、physics、risk、recorder 或 frontend 职责塞进模块 D。
