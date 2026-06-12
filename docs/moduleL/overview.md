# Module L Overview：数据记录与导出边界

## 职责

Module L 是仿真系统的数据出口层。它消费 A-K 在 episode 运行期间或 episode 完成后产出的结构化对象，按固定 schema 写入 Parquet、JSONL、manifest 和 summary 文件，并构造前端展示用的 `SimFrame` 与单 episode 指标 `EpisodeSummary`。

L 的核心原则是只观察和落盘。它不得改变 `CraneState`、`Task.status`、`ExecutedCommand`、`ControlTarget`、`OnlineRisk` 或离线标签，也不得补全、纠正或重新解释上游对象。输入对象不合法或写入失败时，L 应抛出 data export error，并避免留下半截权威数据。

## 文件结构

每个 run 使用总方案 L.1 的目录结构：

```text
runs/{exp_id}/
  config/
    resolved_config.yaml
    scenario.yaml
    experiment.yaml
    dataset.yaml
  metadata/
    episode_metadata.json
    episode_summary.json
    dataset_summary.json
  logs/
    llm_observations.jsonl
    llm_decisions.jsonl
    commands.jsonl
    interventions.jsonl
    events.jsonl
  data/
    trajectories.parquet
    pair_risks.parquet
    graph_edges.parquet
    tasks.parquet
    weather.parquet
  replay/
    command_replay.jsonl
  visual/
    frames.jsonl
    episode_manifest.json
    preview.mp4
    screenshots/
```

MVP 必须创建 `config/`、`metadata/`、`logs/`、`data/`、`replay/`、`visual/` 六个目录。`preview.mp4` 和 `screenshots/` 由后续前端/渲染模块生成，L 只预留路径，不负责渲染。

## 全局 Schema 约定

- 所有 JSONL 每行包含 `schema_version`。
- 所有 Parquet 表包含 `schema_version` 列。
- 时间单位为秒，距离单位为米，角度单位为 rad。
- 训练主表使用 Parquet：`trajectories.parquet`、`pair_risks.parquet`、`graph_edges.parquet`、`tasks.parquet`、`weather.parquet`。
- LLM observation、decision、command、intervention 和 event 使用 JSONL 保留原始嵌套结构。
- `visual/frames.jsonl` 是展示权威，不替代训练权威表。
- `trajectories.parquet` 和 `pair_risks.parquet` 是训练/标签权威。
- nullable 字段使用 JSON `null` 或 Parquet nullable column，不用空字符串冒充缺失值。
- NaN/Inf 由 L 统一检测，记录 warning，并在文件中写成 `null`。
- 所有新增 Pydantic schema 使用 `extra="forbid"`，并尽量设置 `allow_inf_nan=False`；需要落盘时再将上游已有非法浮点转换为 `null` 和 warning。

## 输入

L 读取以下上游对象：

- A：`ResolvedConfig`，提供 run 目录、schema version、scenario、experiment、dataset、runtime、output、resolved config hash 等元数据。
- C：`CraneState[]`，每帧物理状态，用于 `trajectories.parquet` 和 `SimFrame.cranes`。
- D：`Task[]`、`TaskQueue[]`、`TaskEventPayload[]`，用于 `tasks.parquet`、`events.jsonl` 和 frame task 摘要。
- E：`WeatherState`、`WeatherVisibilityContext`，用于 `weather.parquet`、trajectory weather 字段和 `SimFrame.weather`。
- F：`Observation`，用于 `logs/llm_observations.jsonl`。
- G：`RawLLMResponse`、`ParsedCommand`、`LLMCallRecord`，用于 `commands.jsonl` 和 `llm_decisions.jsonl`。
- H：`ExecutedCommand`、`OnlineRisk`、`InterventionRecord`、`SafetyEvent`，用于 `commands.jsonl`、`pair_risks.parquet`、`interventions.jsonl`、`events.jsonl` 和 `SimFrame.pairs`。
- I：`ControlTarget`、`ControllerDiagnostic`，用于可选诊断记录和 trajectory 当前执行输入镜像。
- J：`WorldSnapshot` 派生信息、`episode_status`、`frame_index`、`time_s`、当前 commands、task queues 和 frame events。
- K：`OfflineRiskLabel`，episode 完成后用于写入带未来标签列的 `pair_risks.parquet` 或离线回放扩展。

## 输出

L 输出以下权威文件：

- `data/trajectories.parquet`：每帧每塔吊一行，覆盖总方案 L.2 40+ 字段。
- `data/pair_risks.parquet`：每帧每塔吊对一行，覆盖总方案 L.3 当前距离、未来窗口、TTC、risk 和 collision label 字段。
- `data/graph_edges.parquet`：每帧每有向边一行，覆盖总方案 L.4 的 STGNN 物理先验边特征。
- `data/tasks.parquet`：任务状态、时间、deadline、区域和载荷字段。
- `data/weather.parquet`：每帧天气字段。
- `logs/llm_observations.jsonl`：决策时刻 observation 记录。
- `logs/llm_decisions.jsonl`：provider 调用、prompt/messages、raw response、validation errors 和 retry 记录。
- `logs/commands.jsonl`：raw/parsed/executed command 对照、修改原因、latency/token/cache 等。
- `logs/interventions.jsonl`：S2/S3 风险干预、机械/禁区修改等结构化记录。
- `logs/events.jsonl`：至少 25 种 MVP 事件类型。
- `visual/frames.jsonl`：前端离线回放的 `SimFrame` 序列。
- `visual/episode_manifest.json`：回放 manifest。
- `metadata/episode_metadata.json`：episode metadata 骨架与最终 summary 状态。
- `metadata/episode_summary.json`：`EpisodeSummary` 的文件副本。
- `metadata/dataset_summary.json`：数据集聚合阶段由 O 写入，L 可预留，不在单 episode finalize 中生成全量 dataset summary。

## 对外接口

建议新增 `backend/app/schemas/recorder.py` 作为 L 的唯一 schema 源：

```python
RECORDER_SCHEMA_VERSION = "1.0"

class SimFrame(RecorderBaseModel): ...
class EpisodeSummary(RecorderBaseModel): ...
class TrajectoryRow(RecorderBaseModel): ...
class PairRiskRow(RecorderBaseModel): ...
class GraphEdgeRow(RecorderBaseModel): ...
class TaskParquetRow(RecorderBaseModel): ...
class WeatherParquetRow(RecorderBaseModel): ...
class ObservationLogEntry(RecorderBaseModel): ...
class CommandLogEntry(RecorderBaseModel): ...
class DecisionLogEntry(RecorderBaseModel): ...
class InterventionLogEntry(RecorderBaseModel): ...
class EventLogEntry(RecorderBaseModel): ...
class EpisodeManifest(RecorderBaseModel): ...
class DataExportWarning(RecorderBaseModel): ...
```

建议新增 `backend/app/sim/recorder.py`：

```python
class DataExportError(RuntimeError): ...

class Recorder:
    @classmethod
    def from_config(cls, config: ResolvedConfig | object) -> "Recorder": ...

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
    ) -> SimFrame: ...

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
        online_risk: OnlineRisk | None = None,
        observations: Sequence[Observation] = (),
        llm_calls: Sequence[LLMCallRecord] = (),
        interventions: Sequence[InterventionRecord] = (),
        events: Sequence[Mapping[str, Any] | EventLogEntry] = (),
        status: EpisodeStatus | str = "running",
        snapshot_id: str | None = None,
    ) -> SimFrame: ...

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

当前 `backend/app/sim/scheduler.py` 已调用 `record_initial_frame()` 和 `record_step()`，并传入深拷贝对象。Module L 的实现应兼容该调用形态，再逐步扩展 `online_risk`、`observations`、`llm_calls` 等可选输入。

## 对内依赖

- `backend/app/schemas/state.py`：`CraneState`。
- `backend/app/schemas/task.py`：`Task`、`TaskQueue`、`TaskEventPayload`。
- `backend/app/schemas/weather.py`：`WeatherState`、`WeatherVisibilityContext`。
- `backend/app/schemas/observation.py`：`Observation`。
- `backend/app/schemas/command.py`：`RawLLMResponse`、`ParsedCommand`、`ExecutedCommand`、`LLMCallRecord`。
- `backend/app/schemas/risk.py`：`OnlineRisk`、`RiskPairResult`、`InterventionRecord`、`SafetyEvent`、`OfflineRiskLabel`。
- `backend/app/schemas/control.py`：`ControlTarget`、`ControllerDiagnostic`。
- `backend/app/schemas/scheduler.py`：`EpisodeStatus`、`WorldSnapshot` 的时间和状态合同。
- `backend/app/sim/physics.py`：`crane_state_to_trajectory_row()` 作为 trajectory row 的现有基础转换函数。
- Parquet 写入依赖需要在阶段三加入 `pyarrow`；如选择 Pandas 辅助测试，需要同步加入依赖或只用 PyArrow Table/Parquet API。

## 非目标

Module L 不做以下事情：

- 不推进物理状态，不修改 `CraneState`。
- 不修改任务状态、任务队列、任务事件或 recovery 逻辑。
- 不构造 `Observation`，不调用 LLM provider，不解析 LLM 输出。
- 不进行机械安全、禁区策略、在线风险评估或安全干预。
- 不把 `ExecutedCommand` 转为 `ControlTarget`。
- 不冻结 `WorldSnapshot`，不决定 frame loop 顺序。
- 不计算 `OfflineRiskLabel`，只写入 K 的输出。
- 不生成 dataset split，不做 STGNN window slicing。
- 不渲染 3D 前端，不推送 WebSocket；N/M 只消费 L 产出的 `SimFrame` schema。
- 不在输入不合法时静默补全字段。

## 失败边界

| 失败 | 默认处理 |
| --- | --- |
| run 目录创建失败 | 抛出 `DataExportError(category="data_export_error")`，不启动 recorder |
| schema 校验失败 | 抛出 `DataExportError`，定位 episode/frame/file/field |
| 写入 JSONL 失败 | 保持当前文件句柄可关闭，抛出 `DataExportError` |
| 写入 Parquet 失败 | 使用临时文件/分片 flush 策略，避免替换已有权威文件为半截文件 |
| NaN/Inf | 记录 `DataExportWarning`，落盘为 `null`，summary 标记 `has_nan` 或 `has_inf` |
| offline label 泄漏到实时 frame | schema/构造器拒绝，测试必须覆盖 |
| finalize 失败 | 抛出 `DataExportError`，已写入的分片保持可诊断，不写假的完成 summary |

## 权威来源

若本文档与根目录 `群塔LLM仿真系统开发方案_v0.4_完整版.md` 或 `目标.md` 冲突，以总方案 `0.7.1`、`0.7.2`、`0.7.3`、`L.1` 到 `L.9` 以及本轮 `目标.md` 为准，并同步修订本文档。
