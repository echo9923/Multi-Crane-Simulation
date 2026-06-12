# Task 07：Recorder Orchestrator

## 任务目标

组装完整 `Recorder`，让 Module J 可以按 `record_initial_frame()`、`record_step()`、`finalize()` 调用 L，实现逐帧落盘、视觉帧输出和最终 summary。

## 范围：做什么 / 不做什么

做：

- 在 `backend/app/sim/recorder.py` 实现 `Recorder`。
- 实现 `Recorder.from_config(config)`。
- 在初始化时调用 Task 02 的 run directory setup。
- 持有 Task 03 的 Parquet writers、Task 04 的 JSONL writers、Task 05 的 visual writer、Task 06 的 stats accumulator。
- 实现 `record_initial_frame()`，在 `time_s=0`、`frame_index=0` 记录初始状态。
- 实现 `record_step()`，记录每帧 trajectories、weather、events、commands、risk、visual frame。
- 实现 `write_offline_labels()`，写入 K 产出的 `OfflineRiskLabel` 到 `pair_risks.parquet` 的 future/offline 字段。
- 实现 `finalize(episode_status) -> EpisodeSummary`，flush/close writers、写 manifest、计算 summary。
- 保证 recorder 不修改传入对象。

不做：

- 不改变 J 的 frame loop 顺序。
- 不生成 observation、LLM decision、ExecutedCommand、ControlTarget、OnlineRisk 或 OfflineRiskLabel。
- 不在 recorder 内决定 terminal status。
- 不做 dataset split 或 STGNN window slicing。
- 不推送 WebSocket。

## 接口与数据结构（签名级别）

```python
class Recorder:
    def __init__(
        self,
        *,
        layout: RunDirectoryLayout,
        scenario_id: str | None,
        resolved_config: ResolvedConfig | Mapping[str, Any] | None,
        parquet_writers: RecorderParquetWriters,
        jsonl_writers: RecorderJsonlWriters,
        visual_writer: VisualFrameWriter,
        stats: EpisodeStatsAccumulator,
    ) -> None: ...

    @classmethod
    def from_config(cls, config: ResolvedConfig | Mapping[str, Any] | object) -> "Recorder": ...
```

`record_initial_frame()` 必须兼容当前 `EpisodeRunner._record_initial_frame()`：

```python
def record_initial_frame(
    self,
    *,
    episode_id: str,
    frame_index: int,
    time_s: float,
    states: Sequence[CraneState],
    weather_state: WeatherState,
    visibility_context: WeatherVisibilityContext | None = None,
    commands: Mapping[str, ExecutedCommand] | None = None,
    task_queues: Sequence[TaskQueue] = (),
    events: Sequence[Mapping[str, Any] | EventLogEntry] = (),
    status: EpisodeStatus | str = "running",
    **extra: Any,
) -> SimFrame: ...
```

`record_step()` 必须兼容当前 `EpisodeRunner._run_one_frame()`：

```python
def record_step(
    self,
    *,
    episode_id: str,
    frame_index: int,
    time_s: float,
    states: Sequence[CraneState],
    weather_state: WeatherState,
    visibility_context: WeatherVisibilityContext | None = None,
    commands: Mapping[str, ExecutedCommand] | None = None,
    control_targets: Sequence[ControlTarget] = (),
    controller_diagnostics: Sequence[ControllerDiagnostic] = (),
    task_queues: Sequence[TaskQueue] = (),
    events: Sequence[Mapping[str, Any] | EventLogEntry] = (),
    status: EpisodeStatus | str = "running",
    snapshot_id: str | None = None,
    online_risk: OnlineRisk | None = None,
    observations: Sequence[Observation] = (),
    llm_calls: Sequence[LLMCallRecord] = (),
    interventions: Sequence[InterventionRecord] = (),
    **extra: Any,
) -> SimFrame: ...
```

```python
def write_offline_labels(
    self,
    labels: Sequence[OfflineRiskLabel],
) -> None: ...

def finalize(
    self,
    *,
    episode_status: EpisodeStatus | str,
) -> EpisodeSummary: ...
```

转换 helper：

```python
def trajectory_rows_from_states(
    *,
    episode_id: str,
    scenario_id: str | None,
    frame_index: int,
    time_s: float,
    states: Sequence[CraneState],
    commands: Mapping[str, ExecutedCommand] | None,
    weather_state: WeatherState | None,
) -> list[TrajectoryRow]: ...
```

```python
def pair_rows_from_online_risk(
    *,
    episode_id: str,
    scenario_id: str | None,
    frame_index: int,
    time_s: float,
    online_risk: OnlineRisk | None,
) -> list[PairRiskRow]: ...
```

```python
def pair_rows_from_offline_labels(
    labels: Sequence[OfflineRiskLabel],
) -> list[PairRiskRow]: ...
```

```python
def task_rows_from_queues(
    *,
    episode_id: str,
    scenario_id: str | None,
    task_queues: Sequence[TaskQueue],
) -> list[TaskParquetRow]: ...
```

事务/失败策略：

- 每个 `record_step()` 先构造并校验所有 row/log/frame。
- 构造全部成功后再写入各 writer。
- 任一 writer 失败时抛出 `DataExportError`。
- 不回写或修改传入 `states`、`task_queues`、`commands`。

## 前置依赖

- Task 01-06。
- 当前 `backend/app/sim/scheduler.py` 的 `EpisodeRunner` 调用合同。
- `backend/app/sim/physics.py::crane_state_to_trajectory_row()`。
- `backend/app/tests/test_moduleJ_acceptance.py` 中 `FakeRecorder` 的接口参考。

## 验收标准（具体、可测试）

- `Recorder.from_config()` 创建目录和 writers。
- `record_initial_frame()` 只接受 `time_s=0`、`frame_index=0`；其他值失败。
- `record_initial_frame()` 写入 trajectories、weather、visual frame 和 stats。
- `record_step()` 写入 trajectories、weather、events、commands、pair risks、visual frame。
- `record_step()` 在不传 `online_risk` 时仍可记录 trajectory/weather/frame，pair risks 为空或 null 策略明确。
- `record_step()` 兼容当前 `EpisodeRunner` 传入的参数。
- `write_offline_labels()` 将 K 的 `OfflineRiskLabel` 转为 `PairRiskRow`，包含 5/10/15 秒字段。
- `finalize()` flush/close 所有 writers，写 manifest 和 summary。
- 传入对象在调用前后 `model_dump()` 相同，证明 recorder 只观察。
- 写入失败抛出 `DataExportError`，不静默吞错。

## 测试要点（正常 + 边界 + 异常）

- 正常：tmp run 下记录 initial + 2 step + finalize，读回所有必需文件。
- 正常：与 `EpisodeRunner` fake dependencies 集成，runner 调用真实 `Recorder`。
- 正常：offline labels 在 episode 后写入 pair risks。
- 边界：单塔吊时 pair risks 为空，仍能 finalize。
- 边界：无 task queues 时 tasks parquet 为空或不创建，策略需与 Task 03 保持一致。
- 异常：`record_initial_frame(time_s=0.5)` 失败。
- 异常：writer 抛错时 `record_step()` 抛 `DataExportError`。
- 防越界：调用后比较输入 `CraneState`、`TaskQueue`、`ExecutedCommand` 未变。

## 依赖关系

Task 07 依赖 Task 01-06，是 Module L 的集成任务。Task 08 对 Task 07 做完整验收。
