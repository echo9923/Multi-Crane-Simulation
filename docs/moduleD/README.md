# 模块 D：任务生成与任务状态机模块任务索引

## 为什么下一个拆模块 D

模块 A 已经提供稳定的 `ScenarioConfig`、`ExperimentConfig`、`ResolvedConfig` 和 `seeds.task`，模块 B 已经输出可仿真的 `CraneConfig[]`，模块 C 已经能初始化并推进 `CraneState[]`。模块 D 是把“能动的塔吊”变成“任务驱动仿真”的第一层：它生成每台塔吊的任务队列，并在运行时根据吊钩位置、速度、LLM 的 `task_action` 请求和计时器推进任务状态。

最小链路是：

```text
ResolvedConfig + CraneConfig[] + site zones + load_types
  -> Task[]
  -> per-crane TaskQueue
  -> TaskManager.step_after_physics(states, task_actions, time_s)
  -> Task.status / CraneState.task_stage / load_attached fields / task events
```

模块 D 的边界必须清楚：它回答“当前每台塔吊要做什么任务、任务是否可以开始、是否满足挂载/卸载条件、任务是否完成或失败”，不回答“司机应该怎样开”“下一帧物理状态如何变化”“多塔风险等级是多少”“数据怎样落盘”。

权威来源为项目根目录下的 `群塔LLM仿真系统开发方案_v0.4_完整版.md`。若本文档与总方案冲突，以总方案中 `0.5.6`、`0.5.7`、`0.6.2`、`0.6.3`、`0.7.7`、`0.7.8`、`0.8.6`、`模块 D`、`15.3` 和 `15.8 ISSUE-006` 的合同约定为准，并同步修订本文档。

## 模块目标

模块 D 负责：

- 定义运行时 `Task`、`TaskQueue`、`TaskStatus`、`TaskStage` 和任务事件合同。
- 根据 material/work zones、load types、塔吊布局和任务配置生成任务。
- 支持 `easy_task`、`overlap_task`、`stress_task` 三类普通任务。
- 支持每台塔吊独立任务队列，不做任务抢占、双机抬吊或多塔协商分配。
- 对生成任务执行 pickup/dropoff 可达性、禁区、载重和力矩校验。
- 支持 `simultaneous`、`staggered`、`scheduled` 三种队列启动策略。
- 在仿真运行时推进 `Task.status` 和 `CraneState.task_stage`。
- 抽象挂载/卸载流程：LLM 请求、任务系统判定、pending 延迟、条件漂出取消、完成后更新载荷字段。
- 记录 deadline missed、attach/release rejected、task started/completed/failed、recovery release 等任务事件。
- 在 release 失败且仍带载时进入 `recovery_release`，未卸载前不得启动下一普通任务。

## 分阶段边界

模块 D 属于 M1 的核心交付，但可分成两层完成：

- M1a：任务对象、任务生成、可行性校验、队列启动。完成后可以在 episode 启动前得到确定性的 per-crane `Task[]`。
- M1b：运行时状态机、挂载/卸载、deadline、失败恢复、事件接口。完成后调度器可以让规则司机或 LLM 在真实任务中工作。

M1 完整链路需要模块 I/J/L/F/G/H 的后续接入，但模块 D 自身的验收不依赖真实 LLM provider。D 可以通过最小 `TaskActionSignal`、`CraneState` 和 fake clock 做单元测试。

## 模块边界

模块 D 的输入：

- `ResolvedConfig.tasks.generation`
- `ResolvedConfig.seeds.task`
- `ScenarioConfig.site.material_zones`
- `ScenarioConfig.site.work_zones`
- `ScenarioConfig.site.forbidden_zones`
- `ScenarioConfig.site.forbidden_zone_policy`
- `ScenarioConfig.site.boundary`
- `ScenarioConfig.load_types`
- `CraneConfig[]`，来自模块 B。
- `LayoutReachabilityReport`，来自模块 B 的预检查，可作为诊断参考。
- 当前帧后验 `CraneState[]`，来自模块 C 的物理 step。
- 当前决策周期的 `ExecutedCommand.task_action` 或等价 `TaskActionSignal`，来自模块 G/I/J。
- `time_s`、`dt`、episode lifecycle 调用顺序，来自模块 J。

模块 D 的输出：

- `Task[]`
- `TaskQueue[]`
- `TaskGenerationReport`
- 每台塔吊当前 active task 或 idle 状态。
- 更新后的 `Task.status`、`started_at_s`、`completed_at_s`、`failed_at_s`、`failure_reason`、`deadline_missed`、`overtime_s`。
- 更新后的任务权威字段：`CraneState.task_id`、`CraneState.task_stage`、`load_attached`、`load_type`、`load_weight_t`、`load_size_m`。
- 任务事件：`task_started`、`task_completed`、`task_failed`、`deadline_missed`、`attach_request_rejected`、`release_request_rejected`、`attach_pending_cancelled`、`release_pending_cancelled`、`load_attached`、`load_released`、`recovery_release_started` 等。
- `TASK_*` 错误、warning 和 diagnostic。

模块 D 可在任务生成阶段从 `CraneConfig[]` 派生轻量 `TaskOverlapRegion`，用于 `overlap_task` 和 `stress_task` 的采样。该对象只服务任务采样，不回写布局，不替代模块 B 的 `LayoutDiagnostics`，也不计算风险等级。

模块 D 允许修改：

- `Task.status` 与 Task runtime metadata。
- `CraneState.task_id`。
- `CraneState.task_stage`。
- 挂载/卸载完成瞬间的 `CraneState.load_attached`、`load_type`、`load_weight_t`、`load_size_m`。

模块 D 不允许做的事情：

- 不生成 `CraneConfig` 或重新校验塔吊布局。
- 不积分或更新回转、小车、吊钩高度等物理运动字段。
- 不把 joystick/gear/LLM command 转成速度或 `ControlTarget`。
- 不调用真实 LLM provider。
- 不计算 online risk、near-miss、collision 或 offline label。
- 不做多塔抢同一任务、双机抬吊或全局路径规划。
- 不替 LLM 静默接管 idle 阶段的动作。
- 不写 `trajectories.parquet`、`tasks.parquet`、`events.jsonl` 或前端 frame；这些由 recorder 模块消费 D 的对象和事件后落盘。

## 拥有对象

模块 D 拥有并写入：

- `Task`
- `TaskPoint`
- `TaskStatus`
- `TaskStage`
- `TaskQueue`
- `TaskGenerationReport`
- `TaskRuntimeDiagnostic`
- `TaskActionSignal` 的读取侧合同
- 任务生成器
- 任务可行性校验器
- 队列 scheduler
- attach/release 状态机
- recovery release 管理器
- 任务侧事件 payload
- `TASK_*` 错误码

模块 D 只读取或接收接口，不拥有：

- `ScenarioConfig`、`ExperimentConfig`、`ResolvedConfig` 的配置 schema 定义，归模块 A。若 D 需要补字段，必须作为配置合同扩展同步更新模块 A。
- `CraneModelSpec`、`CraneConfig`、`LayoutReachabilityReport`，归模块 B。
- `CraneState` 的运动字段，归模块 C。
- `ExecutedCommand`、`ParsedCommand`、`RawLLMResponse`，归模块 G/I。
- `ControlTarget`，归模块 I。
- `EpisodeStatus`、单帧生命周期和终止判定，归模块 J。
- `OnlineRisk` / `OfflineRiskLabel`，归模块 H/K。
- `FrameRecord`、`SimFrame`、Parquet/JSONL 文件，归模块 L。

## 与相邻模块的接口

| 相邻模块 | 模块 D 读取什么 | 模块 D 提供什么 | 明确不做什么 |
| --- | --- | --- | --- |
| A 配置与实验管理 | `tasks` 配置、zone/load type 配置、`seeds.task` | 对缺失的 D 配置合同提出 schema 扩展需求 | 不解析原始 YAML，不回写 resolved config |
| B 布局与型号库 | `CraneConfig[]`、capacity/load chart、reachability report | 具体 `Task[]` 与任务可行性错误 | 不生成布局，不改变塔吊型号 |
| C 物理 | 后验 `CraneState[]` | 更新 task/load 权威字段后的状态副本 | 不推进物理运动字段 |
| F/G 操作员/LLM | `task_action`、命令 ID、idle 动作摘要 | 当前任务、阶段、信号提示和历史事件供 observation 使用 | 不调用 LLM，不解析完整 raw response |
| I 控制器 | 无直接依赖，可接收执行后命令摘要 | 当前 task/stage 供控制器或规则司机读取 | 不生成 `ControlTarget` |
| J 调度器 | `time_s`、调用顺序、episode status 容器 | task events、runtime errors、是否所有普通任务完成 | 不决定 collision/timeout 等全局终止 |
| H/K 风险 | 无直接依赖 | 当前任务点和任务阶段可作为风险上下文 | 不计算风险等级 |
| L recorder | 无直接依赖 | 可序列化 `Task`、queue snapshot、task events | 不写文件 |
| N 前端 | 无直接依赖 | 任务点、阶段、事件由 recorder/API 间接暴露 | 不做展示坐标转换 |

## 数据对象边界

### Task.status 与 CraneState.task_stage

`Task.status` 是任务队列状态，只能取：

```text
pending / active / completed / failed / skipped
```

`CraneState.task_stage` 是塔吊当前执行阶段，只能取：

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

`pending` 不得作为 `task_stage` 使用。`idle` 不得作为 `Task.status` 使用。

M1 默认不产生 `skipped`。该状态只作为 manual task 容错策略预留；只有未来显式配置 `invalid_manual_task_policy=skip` 时，模块 D 才能把无效 manual task 标记为 `skipped`。auto generation 不得用 skipped 掩盖任务生成失败。

### 普通任务与恢复任务

普通生成任务类型：

```text
easy_task / overlap_task / stress_task
```

运行时恢复任务类型：

```text
recovery_release
```

`recovery_release` 不是用户任务分布的一部分，不得出现在 `task_type_distribution` 中。它只在 release 失败且仍带载时由 TaskManager 创建或激活，并必须包含 `source_failed_task_id`。

## 错误码边界

模块 D 最低错误码：

```text
TASK_E_001 task pickup/dropoff 不可达 -> 默认 startup_error；只有显式 manual skip policy 才能 task skipped。
TASK_E_002 task 天然超载或超力矩 -> startup_error 或重新采样；不得进入正常 episode。
TASK_E_101 attach_stage_timeout -> task_failed，默认 episode 继续。
TASK_E_102 release_stage_timeout 且 load_attached=false -> task_failed，episode 继续。
TASK_E_103 release_stage_timeout 且 load_attached=true -> task_failed，并进入 recovery_release。
TASK_E_104 recovery_release_timeout -> episode failed_recovery_timeout，由调度器映射。
TASK_E_105 recovery target blocked -> episode failed_recovery_blocked，由调度器映射。
TASK_W_201 deadline_missed -> episode_event，继续运行。
TASK_D_301 attach/release request rejected -> diagnostic/event，当前任务继续。
TASK_D_302 pending cancelled because conditions drifted -> diagnostic/event，当前任务继续。
```

## 任务顺序

| 顺序 | 文档 | 阶段 | 目标 |
|---|---|---|---|
| 1 | [task01_task_schema_contract](task01_task_schema_contract.md) | M1a | 定义 `Task`、状态枚举、速度阈值配置补齐和任务事件合同 |
| 2 | [task02_task_generation_sampling](task02_task_generation_sampling.md) | M1a | 根据 zones、load types、分布和 seed 生成 per-crane 普通任务 |
| 3 | [task03_task_feasibility_validation](task03_task_feasibility_validation.md) | M1a | 对具体任务执行可达、禁区、载重和力矩校验 |
| 4 | [task04_task_queue_scheduler](task04_task_queue_scheduler.md) | M1a/M1b | 实现每台塔吊独立队列和 simultaneous/staggered/scheduled 启动 |
| 5 | [task05_attach_release_state_machine](task05_attach_release_state_machine.md) | M1b | 实现任务阶段推进、attach/release pending 和载荷字段更新 |
| 6 | [task06_deadline_failure_recovery](task06_deadline_failure_recovery.md) | M1b | 实现 deadline、timeout、失败处理和 recovery_release 合同 |
| 7 | [task07_signal_observation_event_contract](task07_signal_observation_event_contract.md) | M1b | 定义地面信号提示、observation 读取边界和事件 payload |
| 8 | [task08_tests_and_acceptance](task08_tests_and_acceptance.md) | M1 | 定义模块 D 的测试清单、集成合同和验收标准 |

## 全局实现约束

- 所有任务生成必须使用 `seeds.task`，同一 resolved config 必须得到确定性任务队列。
- 每台塔吊有自己的任务队列；每个普通任务只分配给一台塔吊。
- 不得硬编码 C1/C2/C3，必须支持 N 台塔吊。
- pickup 必须来自 material zones，dropoff 必须来自 work zones。
- `load_type` 必须来自场景 `load_types`，并同时满足 pickup zone `load_types` 与 dropoff zone `accepted_load_types`。
- pickup/dropoff 不得落入 forbidden zones。
- pickup/dropoff 必须落在 `site.boundary` 内。
- 生成阶段必须避免天然不可达、天然超载或超力矩任务进入正常 episode。
- `priority` 和 `deadline_s` 进入 observation/prompt，但不改变物理规则。
- `deadline_missed` 不导致任务失败，不导致 episode 终止。
- attach/release 只能由 LLM 的 `task_action` 请求触发，但是否进入 pending 由任务系统判定。
- pending 期间条件漂出阈值必须取消 pending，记录事件，并回到对应 lower 阶段。
- release 失败且仍带载时必须进入 `recovery_release`，不得清空载荷，也不得启动下一普通任务。
- Task 06 负责创建 recovery task、选择 recovery target 和处理 recovery timeout；Task 05 负责执行普通 release 与 recovery release 共用的 release 判定、pending 延迟和载荷清空。
- 任务系统只在挂载/卸载完成瞬间修改载荷权威字段。
- idle 阶段仍然允许操作员被调用；D/J/G 不得提前告诉操作员下一任务信息。

## M1 最小交付结果

完成 Task 01-08 后，后续模块应能：

1. 从 resolved config、布局和 site zones 生成确定性的 per-crane `Task[]`。
2. 支持 `easy_task`、`overlap_task`、`stress_task`。
3. 支持 `simultaneous`、`staggered`、`scheduled` 队列启动。
4. 在运行时推进 `pending -> active -> completed/failed`，并在显式 manual skip policy 下支持 `skipped`。
5. 在 `CraneState.task_stage` 中表达当前执行阶段。
6. 正确处理 request_attach/request_release、pending 延迟、条件漂出取消和载荷字段更新。
7. 正确记录 deadline missed，不把 deadline 当成失败。
8. 正确处理 attach/release timeout 和 recovery release。
9. 输出可被 recorder 和前端消费的任务事件。
10. 用规则司机或最小 fake operator 完成至少 80% easy_task，用于验证任务生成合理性。
