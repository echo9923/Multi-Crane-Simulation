# 模块 J：仿真调度器任务索引

## 模块目标

模块 J 管理完整 episode 主循环：按固定单帧生命周期调用全部模块，维护仿真时钟与 `episode_status`，冻结 `WorldSnapshot`，同步应用同一 decision time 的多塔命令，处理命令过期、replay、记录推送和终止条件。

J 是调度指挥中心，不是任务、安全、LLM、控制器、物理或 recorder 的业务实现层。

权威来源为项目根目录下的 `目标.md` 和 `群塔LLM仿真系统开发方案_v0.4_完整版.md`。若本文档与总方案冲突，以总方案 `0.7.2`、`0.7.3`、`0.7.8`、`0.7.9`、`模块 J` 以及本轮 `目标.md` 为准，并同步修订本文档。

## 模块边界

模块 J 的输入：

- `ResolvedConfig` / `ExperimentConfig` / `SimConfig`。
- `CraneConfig[]`、`CraneModelSpec`。
- `CraneState[]`。
- `Task[]`、`TaskQueue[]`、任务激活与状态机接口。
- `WeatherGenerator` / `WeatherState`。
- `Observation` 构造接口。
- LLM/rule/replay operator 决策接口。
- safety pipeline、online risk、collision detection。
- controller、physics、recorder、WebSocket 推送接口。

模块 J 的输出：

- episode clock：`time_s`、`frame_index`。
- `WorldSnapshot`。
- `EpisodeStatus`。
- `SchedulerConfig`。
- `CommandStore` 当前执行命令。
- `EpisodeResult` / `FrameStepResult`。
- recorder/API/WebSocket 可消费的调度层状态。

模块 J 允许修改：

- 调度器内部时间、frame index、状态机状态。
- 当前命令存储。
- `episode_status`。
- 由 J 创建的 `WorldSnapshot` 与调度结果对象。

模块 J 不允许做：

- 不实现任务状态机业务规则。
- 不实现天气生成。
- 不构造 observation 细节。
- 不调用具体 LLM provider。
- 不解析 LLM JSON 或 schema retry。
- 不做 safety、risk、controller、physics 的业务计算。
- 不写 recorder 文件格式。
- 不生成 offline risk label。
- 不为 rule/LLM/replay 分叉出不同 frame loop。

## 任务顺序

| 顺序 | 文档 | 目标 |
|---|---|---|
| 1 | [task01_scheduler_schema](task01_scheduler_schema.md) | 定义 Module J 的 schema 与调度层数据合同 |
| 2 | [task02_world_snapshot_freezer](task02_world_snapshot_freezer.md) | 实现冻结 `WorldSnapshot` 的只读快照合同 |
| 3 | [task03_command_store](task03_command_store.md) | 实现当前 `ExecutedCommand` 存储、批量替换和过期 neutral_stop |
| 4 | [task04_decision_timing](task04_decision_timing.md) | 实现每塔决策时刻判定，idle 也参与同一逻辑 |
| 5 | [task05_frame_loop_orchestrator](task05_frame_loop_orchestrator.md) | 组装完整 `EpisodeRunner` 和 15 步帧循环 |
| 6 | [task06_tests_and_acceptance](task06_tests_and_acceptance.md) | 定义 Module J 单元、验收、回归和端到端测试清单 |

## 依赖关系

```text
Task 01 scheduler schema
  -> Task 02 world snapshot freezer
  -> Task 03 command store
  -> Task 04 decision timing
  -> Task 05 frame loop orchestrator
  -> Task 06 tests and acceptance
```

说明：

- Task 01 定义 schema 和错误/status 合同，是所有后续任务的事实源。
- Task 02 使用 Task 01 的 `WorldSnapshot`，供 F/G/H/L 读取。
- Task 03 使用 Task 01 的 `CommandStore` 合同，供 I/C/D/H/L 读取当前命令。
- Task 04 使用 Task 01 的 `SchedulerConfig` 和 decision state，供 Task 05 调度决策。
- Task 05 组装 Task 02-04 和所有相邻模块公开接口。
- Task 06 只定义测试与验收，不新增生产接口。

## 全局实现约束

- `WorldSnapshot` 的 Pydantic schema 是唯一事实源，`extra="forbid"`，拒绝 NaN/Inf。
- 同一 `decision_time` 的多塔 observation 必须来自同一 `WorldSnapshot`。
- 同一 `decision_time` 的多塔命令必须收齐后同时应用。
- `command_duration_s` 到期后若无新命令，自动进入系统 `neutral_stop`。
- LLM 超时后默认 neutral_stop；连续失败达到阈值后 `episode_status=llm_failed`。
- `offline_wait` 模式下仿真时间可暂停等待 LLM 返回。
- `realtime_stale` 模式下超时可使用上一命令，但命令过期后仍必须 neutral_stop。
- replay 模式不调用 LLM，不调用 summary LLM，不重新叠加 S2/S3 干预。
- replay 必须检查 config hash、command schema version、physics schema version 和 operator assignment hash 或等价元数据。
- 碰撞检测触发后 `episode_status=failed_collision`，立即终止，不生成碰撞后轨迹。
- NaN/Inf 状态映射为 `failed_invalid_state`。
- 规则司机和 LLM 司机必须使用同一 frame loop。
- `record_initial_frame` 在 `time_s=0` 执行。
- 每次 `record_step` 必须在 physics step 之后、终止判定退出之前执行。
- 事件归属到检测到该事件的 step 后帧。
- `WorldSnapshot` 不得包含 future label、offline risk label 或 LLM reason。

## 最小交付结果

完成 Task 01-06 后，后续模块应能：

1. 从 resolved config 创建 `EpisodeRunner`。
2. 初始化 world state、weather、tasks、command store 和 recorder。
3. 以同一个主循环运行 `offline_batch`、`offline_replay` 和 `interactive_server`。
4. 在每个决策时刻冻结一致 `WorldSnapshot`。
5. 对 due cranes 批量构造 observation、决策、safety、command store 更新。
6. 对未决策 crane 执行命令过期和 neutral_stop。
7. 调用 controller 与 physics 推进到 step 后状态。
8. 调用任务状态机、风险、碰撞、记录和 WebSocket 推送。
9. 正确输出 completed、timeout、failed_collision、failed_invalid_state、llm_failed、failed_replay_mismatch、stopped_by_user 等状态。
10. 为 Module L/O/P 的记录、replay 和数据集生成提供稳定调度结果。
