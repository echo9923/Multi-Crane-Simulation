# Module J Overview：仿真调度器边界

## 职责

模块 J 是 episode 的主循环 owner。它维护仿真时钟、frame index、`episode_status` 和当前执行命令集合，在每一帧按固定顺序调用 A-I、K/L/N 等模块公开接口，并在决策时刻冻结只读 `WorldSnapshot`，保证同一 `decision_time` 的多塔 observation 来自同一个状态切片。

J 的核心问题不是“司机应该怎么开”或“风险如何计算”，而是：

- 当前帧应该先调用哪个模块、后调用哪个模块。
- 哪些塔吊在当前 `time_s` 到达决策时刻。
- 决策时刻看到的世界快照是否一致、冻结、无未来信息。
- 多塔同批命令是否收齐后同时进入 safety/controller/physics 链路。
- 命令何时过期，过期后如何注入系统 `neutral_stop`。
- 模块失败如何映射为统一 episode terminal status。
- episode 何时 completed、timeout、failed 或 stopped。

命令链路在 J 内只被编排，不被重新解释：

```text
Observation
  -> ParsedCommand
  -> ExecutedCommand
  -> ControlTarget
  -> CraneState
  -> recorder / SimFrame
```

## 单帧生命周期

J 必须按总方案 `0.7.8` 执行单帧生命周期。推荐记录初始状态为 `frame=0,time_s=0`；循环内从 `state_t` 积分到 `state_{t+dt}`，并把后验状态记录为下一帧。

```text
0. 已有 state_t；若 t=0，先 record_initial_frame。
1. update_weather(t)。
2. task scheduler 激活到达 planned_start_s / inter_task_delay 的任务。
3. 判断哪些 crane 到达 LLM/rule 决策时刻；idle 阶段也参与判断。
4. 冻结 WorldSnapshot_t，所有同一 decision_time 的 observation 基于同一快照。
5. 基于 snapshot 计算 online_risk_predecision_t，R1 时进入 observation。
6. 并行构造 observation，并行请求 LLM / rule / replay。
7. 解析 raw response，执行 schema retry；失败则生成 neutral_stop ParsedCommand。
8. safety/intervention pipeline 同步生成所有 crane 的 ExecutedCommand。
9. 对未重新决策的 crane 检查 command expiry / stale policy，必要时 neutral_stop。
10. low-level controller 将 ExecutedCommand 转成 ControlTarget。
11. physics/kinematics step 到 state_{t+dt}。
12. task state machine 基于 state_{t+dt} 更新阶段、挂载/卸载、任务事件。
13. risk_now 与 collision detection 基于 state_{t+dt} 计算；collision 生成 terminal event。
14. recorder 写入 frame、trajectory、pair risk、events、commands，WebSocket 推送 SimFrame。
15. 若 terminal status 或 completion cooldown 满足条件则结束；否则 t += dt。
```

关键时间归属：

- `WorldSnapshot.time_s` 是 step 前决策时刻 `t`。
- LLM observation 使用 step 前 snapshot，不使用 step 后状态。
- 普通 frame 记录 step 后状态，`time_s=t+dt`。
- 任务完成、collision、near-miss、invalid state 等事件归属到检测到事件的 step 后帧。
- `record_step` 必须在 physics step 后、终止判定最终退出前执行。
- offline future label 只能在 episode 后生成，绝不进入 `WorldSnapshot` 或 `Observation`。

## 快照冻结策略

`WorldSnapshot` 是模块 J 拥有的只读对象。它服务 F/G/H/L 的同一决策时刻读取，不是可变世界状态。

最小内容：

```text
schema_version
snapshot_id
episode_id
frame_index
time_s
decision_time_bucket
crane_states
crane_configs
weather_state
visibility_context
tasks
task_queues
task_contexts
current_commands
recent_decisions
recent_events
```

冻结规则：

- 使用 deep copy / Pydantic validation 构造快照，构造后不可变。
- 同一 decision batch 中所有 observation 的 `source_snapshot_id` 必须相同。
- snapshot 中不包含 LLM reason、offline risk label、future min distance、未来任务计划或 replay/audit-only summary。
- snapshot 可以包含当前已发生的 events、recent decisions、当前 task context 和当前 command 摘要。
- F 需要的窄输入 `ObservationWorldSnapshot` 应由 J 从 `WorldSnapshot` 派生，不让 F 回读可变运行态。

## 运行模式

J 支持三种 `RuntimeMode`，对应 `backend/app/schemas/enums.py` 中已有枚举：

```text
offline_batch
offline_replay
interactive_server
```

`offline_batch`：

- 不依赖前端 WebSocket。
- 可以使用 mock/rule/no-LLM driver 生成数据。
- 支持加速运行，不按墙钟睡眠。
- 仍执行同一单帧生命周期，不开第二套调度逻辑。

`offline_replay`：

- 读取历史 `command_replay.jsonl` 中的 `ExecutedCommand`。
- 不调用 operator LLM，不调用 summary LLM。
- 不重新叠加 S2/S3 风险干预；历史 `ExecutedCommand` 已是权威执行命令。
- 启动前检查 `resolved_config_hash`、`command_schema_version`、`physics_schema_version`、operator assignment hash 或等价元数据。
- replay 可运行 mechanical/safety audit，但 audit 只能发现 mismatch，不能改写 replay 命令。

`interactive_server`：

- 由模块 M/API 启动、停止、查询 episode。
- 每帧或按前端节流策略生成 `SimFrame`，由模块 N 推送。
- 实时模式可按墙钟节奏运行，也可在后端内部保持同一 frame loop。

注意：`offline_wait` 和 `realtime_stale` 是 LLM scheduling policy，不是 `RuntimeMode`。J 读取该策略决定 LLM 延迟时是否暂停仿真时间或暂用旧命令。

## 输入

J 读取以下上游公开接口和对象：

- A：`ResolvedConfig`，包括 `sim.dt`、`duration_s`、`min_duration_s`、`stop_when_all_tasks_done`、`completion_cooldown_s`、`controller_hz`、`llm_decision_interval_s`、`RuntimeMode`、operator assignment、R/S 模式、LLM scheduling/fallback 策略。
- B：`CraneConfig[]`、`CraneModelSpec`。
- C：`CraneState[]`、`initialize_world_state()`、`step_world()` 或等价 physics step。
- D：`Task[]`、`TaskQueue[]`、任务激活接口、`step_task_state_machine()`、`all_ordinary_tasks_terminal()`。
- E：`WeatherGenerator.update(time_s)`、`WeatherState`、`WeatherVisibilityContext`。
- F：`ObservationWorldSnapshot`、`build_observations_for_snapshot()`。
- G：`OperatorDecisionOrchestrator.should_decide()`、`decide()`，或 rule/mock/replay driver 的同形接口。
- H：`evaluate_online_risk()`、`apply_safety_pipeline()`，以及 safety/risk/collision 候选状态。
- I：`Controller.compute_batch()`。
- K：`detect_collisions()` 或后续 offline label 入口。
- L：`record_initial_frame()`、`record_step()`、commands/events/weather/frame writer。
- N：`broadcast_sim_frame_if_enabled()`。

## 输出

J 产出或维护：

- episode clock：`time_s`、`frame_index`、`dt_s`。
- `WorldSnapshot`。
- `EpisodeStatus`。
- `SchedulerConfig`。
- `CommandStore` 中的当前 `ExecutedCommand`。
- `EpisodeResult` / terminal summary 的调度层字段。
- 模块失败到 `EpisodeStatus` 的映射。
- 给 recorder/API/WebSocket 的 frame lifecycle 事件和状态。

## 对外接口

建议实现入口：

```python
class EpisodeRunner:
    @classmethod
    def from_config(cls, config: ResolvedConfig, *, dependencies: SchedulerDependencies | None = None) -> "EpisodeRunner":
        ...

    def run_episode(self) -> EpisodeResult:
        ...

    def run_one_frame(self) -> FrameStepResult:
        ...

    def stop(self, reason: str = "stopped_by_user") -> None:
        ...

def freeze_world_snapshot(...) -> WorldSnapshot:
    ...

def should_stop(status: EpisodeStatus, sim_time: float, config: SchedulerConfig) -> bool:
    ...

def update_terminal_status(...) -> EpisodeStatus:
    ...
```

`run_one_frame()` 便于 API、测试和 interactive mode 单步推进；`run_episode()` 是 offline batch/replay 的完整循环入口。

## 对内依赖边界

J 可以协调模块调用顺序，但不能把模块业务规则搬进调度器。

允许：

- 调用 D 的任务激活和状态机接口。
- 调用 H 的 online risk、safety pipeline 和 collision/status 候选结果。
- 调用 I 的 controller batch。
- 调用 C 的 physics step。
- 根据模块抛出的结构化错误设置 `episode_status`。
- 根据 `command_duration_s` 维护命令过期和系统 `neutral_stop`。

不允许：

- 在 J 内计算任务 attach/release 是否成立。
- 在 J 内解析 LLM JSON 或实现 schema retry。
- 在 J 内重写机械限位、禁区、风险干预、碰撞距离或 TTC。
- 在 J 内把 joystick/gear 转换成连续速度。
- 在 J 内积分物理状态。
- 在 J 内写 Parquet/JSONL 的具体格式。
- 为 rule driver、LLM driver、replay driver 写三套不同 frame loop。

## 非目标

模块 J 不做以下事情：

- 不构造 `Observation` 字段细节。
- 不调用具体 LLM provider，不生成 `RawLLMResponse`。
- 不解析命令 JSON，不做 schema retry。
- 不做安全审查、机械限位、禁区策略或风险干预。
- 不将离散命令转为连续速度目标。
- 不积分物理运动方程。
- 不推进任务状态机的业务规则。
- 不生成天气状态。
- 不计算碰撞距离、TTC 或离线风险标签。
- 不写 Parquet/JSONL 文件。
- 不渲染前端 3D 视图。

## 失败边界

J 负责统一映射失败状态：

```text
completed
timeout
failed_collision
failed_invalid_state
llm_failed
failed_replay_mismatch
failed_recovery_blocked
failed_recovery_timeout
stopped_by_user
```

默认映射：

- C/I/F/H/E 等模块发现 NaN/Inf、ID 不一致、schema 构造失败或内部状态不一致：`failed_invalid_state`。
- H/K 碰撞检测返回 collision：`failed_collision`，当前 episode 立即终止，不生成碰撞后轨迹。
- G 连续失败达到阈值：`llm_failed`。
- replay 配置 hash、命令唯一性、schema version、audit 或轨迹容差不一致：`failed_replay_mismatch`。
- D recovery target blocked：`failed_recovery_blocked`。
- D recovery release timeout：`failed_recovery_timeout`。
- 达到 `duration_s` 且未满足 completed：`timeout`。
- 所有普通任务完成且满足 `min_duration_s` 与 `completion_cooldown_s`：`completed`。

## 权威来源

若本文档与根目录 `目标.md` 或 `群塔LLM仿真系统开发方案_v0.4_完整版.md` 冲突，以总方案 `0.6.8`、`0.7.1`、`0.7.2`、`0.7.3`、`0.7.5`、`0.7.8`、`0.7.9`、`J.1`、`J.2`、`J.3`、`J.4` 以及本轮 `目标.md` 为准，并同步修订本文档。
