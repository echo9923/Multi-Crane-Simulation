# Task 05：Frame Loop Orchestrator

## 任务目标

实现 `EpisodeRunner`，组装完整 15 步单帧生命周期，支持 `offline_batch`、`offline_replay`、`interactive_server` 三种运行模式，统一推进 clock、snapshot、decision、safety、controller、physics、task、risk/collision、recording 和 terminal status。

## 范围：做什么 / 不做什么

做：

- 在 `backend/app/sim/scheduler.py` 中实现 `EpisodeRunner`。
- 实现 `EpisodeRunner.from_config(config)`。
- 实现 `run_episode()` 和 `run_one_frame()`。
- 按总方案 `0.7.8` 固定顺序调用各模块公开接口。
- 接入 Task 02 `freeze_world_snapshot()`。
- 接入 Task 03 `CommandStore`。
- 接入 Task 04 `DecisionClock`。
- 实现 `update_terminal_status(...)` 和 `should_stop(...)`。
- 处理 `offline_batch`、`offline_replay`、`interactive_server`。
- 处理 `offline_wait` / `realtime_stale` LLM scheduling policy。
- 映射模块异常到 `EpisodeStatus`。
- 确保 `record_initial_frame(time_s=0)` 和每帧 `record_step()` 的调用时机。

不做：

- 不实现真实 recorder writer。
- 不实现 FastAPI route。
- 不实现 WebSocket transport。
- 不实现真实 LLM provider。
- 不重新实现 D/E/F/G/H/I/K 的业务逻辑。
- 不生成 offline risk label。

## 接口与数据结构（签名级别）

依赖注入建议：

```python
class SchedulerDependencies(BaseModel | dataclass):
    weather: WeatherGenerator | WeatherAdapter
    task_system: TaskSystemAdapter
    observation_builder: ObservationBuilderAdapter
    operator: OperatorDecisionAdapter
    safety: SafetyAdapter
    controller: Controller
    physics: PhysicsAdapter
    risk: RiskAdapter
    collision: CollisionAdapter
    recorder: RecorderAdapter
    websocket: WebSocketAdapter | None = None
    replay: ReplayCommandSource | None = None
```

实现可用 protocol/dataclass，而不要求每个模块已经有同名类；测试中可以用 fake adapter。

核心入口：

```python
class EpisodeRunner:
    @classmethod
    def from_config(
        cls,
        config: ResolvedConfig,
        *,
        dependencies: SchedulerDependencies | None = None,
    ) -> "EpisodeRunner":
        ...

    def run_episode(self) -> EpisodeResult:
        ...

    def run_one_frame(self) -> FrameStepResult:
        ...

    def stop(self, reason: str = "stopped_by_user") -> None:
        ...

def update_terminal_status(
    *,
    current_status: EpisodeStatus,
    sim_time: float,
    frame_index: int,
    states: Sequence[CraneState],
    task_queues: Sequence[TaskQueue],
    task_events: Sequence[Any],
    collision_events: Sequence[CollisionEvent],
    llm_results: Sequence[OperatorDecisionResult] = (),
    replay_mismatch: TerminalStatusCandidate | None = None,
    config: SchedulerConfig,
) -> EpisodeStatus | TerminalStatusCandidate:
    ...

def should_stop(
    *,
    episode_status: EpisodeStatus,
    sim_time: float,
    config: SchedulerConfig,
    all_tasks_done_since_s: float | None = None,
) -> bool:
    ...
```

单帧伪代码：

```text
if frame_index == 0 and not initial_recorded:
  weather_0 = weather.update(0)
  recorder.record_initial_frame(time_s=0, state=state_t, weather=weather_0, ...)

1. weather_t = weather.update(sim_time)
2. task_system.activate_due_tasks(sim_time, state_t)
3. decision_cranes = decision_clock.cranes_due_for_decision(sim_time, include_idle=True)
4. if decision_cranes: snapshot_t = freeze_world_snapshot(...)
5. online_risk_predecision = risk.evaluate_online(snapshot_t, command_store.current)
6. observations = F.build_batch(snapshot_t, decision_cranes, online_risk_predecision.hints)
   decisions = operator.decide(observations) or replay source returns ExecutedCommand
7. G handles parse/retry/fallback internally for live modes
8. live modes: safety.apply_pipeline(parsed_commands, snapshot_t) -> executed commands
   replay mode: use historical ExecutedCommand, optional audit-only safety check
   command_store.replace_current_commands(executed_commands, sim_time)
9. command_store.expire_or_neutral_stop(sim_time)
10. control_targets = controller.compute_batch(command_store.current, state_t, models, now_s=sim_time)
11. state_next = physics.step_world(state_t, control_targets, dt)
12. task_events = task_system.update_after_physics(state_next, command_store.current, sim_time + dt)
13. risk_now = risk.evaluate_online(state_next/snapshot_next, command_store.current)
    collision_events = collision.detect(state_next, risk_now)
    status = update_terminal_status(...)
14. recorder.record_step(time_s=sim_time + dt, state=state_next, weather=weather_t, ...)
    websocket.broadcast_sim_frame_if_enabled(...)
15. stop if should_stop(status, sim_time + dt), else advance state_t/state_next and clock
```

`offline_replay` 特别规则：

- 启动前读取并校验 replay metadata。
- 不调用 G。
- 不调用 summary LLM。
- 按 `(decision_index, time_s, crane_id)` 或项目固化键读取唯一历史 `ExecutedCommand`。
- 历史命令进入 `CommandStore.replace_current_commands(..., source="replay")`。
- safety audit 只能产生 mismatch，不能改写命令。
- replay mismatch 映射为 `failed_replay_mismatch`。

LLM scheduling：

- `offline_wait`：决策调用未返回时，仿真时间不推进；测试可用 fake operator 模拟等待。
- `realtime_stale`：短暂延迟可保持上一命令；但 `CommandStore.expire_or_neutral_stop()` 仍要在命令到期后 neutral_stop。
- 单次 LLM timeout 由 G 输出 neutral_stop；连续失败结果由 `OperatorDecisionResult.episode_failure_reason="llm_failed"` 通知 J。

terminal status：

```text
failed_collision:
  collision_events 非空或 H/K 返回 collision candidate。

failed_invalid_state:
  NaN/Inf、physics/controller/observation/safety/weather schema/runtime invalid state。

llm_failed:
  任一 OperatorDecisionResult.episode_failure_reason == "llm_failed"。

failed_replay_mismatch:
  replay validation/audit/command uniqueness/trajectory tolerance mismatch。

failed_recovery_blocked:
  D 返回 recovery target blocked candidate。

failed_recovery_timeout:
  D 返回 recovery release timeout candidate。

completed:
  all_ordinary_tasks_terminal 且满足 min_duration_s 和 completion_cooldown_s。

timeout:
  sim_time >= duration_s 且未 completed/failed。

stopped_by_user:
  stop() 被调用或 API stop request。
```

## 前置依赖

- Task 01-04。
- A-I、K/L/N 的现有公开接口或 fake adapter。
- `RuntimeMode` 和 `LLMSchedulingMode`。
- replay metadata/command source 的最小读取合同。

## 验收标准（具体、可测试）

- `run_one_frame()` 严格按 15 步顺序调用 fake dependencies；测试可记录 call log。
- `record_initial_frame()` 在 `time_s=0` 且 physics step 前调用一次。
- `record_step()` 在 physics step 后、终止退出前调用。
- 同一 decision time 的所有 observations 使用同一 `WorldSnapshot.snapshot_id`。
- 同一 decision time 的多塔命令在 safety pipeline 返回后一次性进入 `CommandStore`。
- 未 due crane 保持旧命令，但过期后 neutral_stop。
- `offline_batch` 不依赖 WebSocket，能跑完整 episode。
- `interactive_server` 可单步运行并调用 WebSocket adapter。
- `offline_replay` 不调用 G/operator LLM，直接使用历史 `ExecutedCommand`。
- replay config hash/schema version mismatch 在启动或首帧映射为 `failed_replay_mismatch` 或 startup error。
- 单次 LLM timeout 产生 neutral_stop 后 episode 继续。
- 连续 LLM 失败达到阈值后 `episode_status=llm_failed`。
- collision 后 `episode_status=failed_collision`，不再生成下一帧轨迹。
- NaN/Inf 状态映射为 `failed_invalid_state`。
- 所有任务完成但未到 `min_duration_s` 时继续记录 idle frame。
- 所有任务完成且 cooldown 满足后 `completed`。
- 达到 `duration_s` 且未完成时 `timeout`。
- rule driver 和 LLM driver 使用同一 `run_one_frame()` 调度路径。

## 测试要点（正常 + 边界 + 异常）

- 正常：fake rule driver 两塔运行 3 帧，call log 顺序完全匹配 0.7.8。
- 正常：mock LLM driver 首帧决策、第二帧未 due、第三帧 due。
- 正常：offline replay 使用两条历史 `ExecutedCommand`，operator fake 断言未被调用。
- 边界：`duration_s == dt_s`，只运行一帧后 timeout/completed。
- 边界：`stop_when_all_tasks_done=false` 时不因任务完成提前 completed。
- 边界：interactive mode 无 websocket adapter 时仍可 run_one_frame。
- 异常：physics adapter 抛 `PhysicsStateError`，J 映射 failed_invalid_state 并记录 terminal event。
- 异常：collision adapter 返回 collision，J 记录当前 step 后帧并终止。
- 异常：replay command 缺失、重复或 schema version 不一致。
- 异常：operator result snapshot id 与 current snapshot 不一致，映射 failed_invalid_state 或 scheduler error。
