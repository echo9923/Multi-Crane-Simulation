# Task 05：SimFrame Builder

## 任务目标

实现 `SimFrame` 构造和离线回放文件写入，使前端离线回放和实时 WebSocket 推送共用同一 schema，并严格隔离 offline labels。

## 范围：做什么 / 不做什么

做：

- 实现 `build_sim_frame()`。
- 实现 `write_visual_frame()`，将 `SimFrame` 追加到 `visual/frames.jsonl`。
- 实现 `build_episode_manifest()` 和 `write_episode_manifest()`。
- 从 `CraneState[]` 构造 `SimFrame.cranes`。
- 从 `OnlineRisk` 或 `PairRiskRow[]` 构造 `SimFrame.pairs`。
- 从 `TaskQueue[]` 或 `Task[]` 构造 frame task 摘要。
- 从 `WeatherState` 构造 `SimFrame.weather`。
- 从 frame events 构造 `SimFrame.events`。
- 支持离线回放可选 `offline_labels`。
- 实时模式下禁止 `offline_labels`。

不做：

- 不写训练 Parquet。
- 不计算 online risk 或 offline labels。
- 不推送 WebSocket。
- 不渲染前端。
- 不把 `visual/frames.jsonl` 作为训练真值替代。

## 接口与数据结构（签名级别）

```python
def build_sim_frame(
    *,
    episode_id: str,
    scenario_id: str | None,
    frame_index: int,
    time_s: float,
    episode_status: EpisodeStatus | str,
    states: Sequence[CraneState],
    weather_state: WeatherState,
    commands: Mapping[str, ExecutedCommand] | None = None,
    pairs: Sequence[PairRiskRow | RiskPairResult | Mapping[str, Any]] = (),
    tasks: Sequence[Task] = (),
    task_queues: Sequence[TaskQueue] = (),
    events: Sequence[EventLogEntry | Mapping[str, Any]] = (),
    offline_labels: Sequence[OfflineRiskLabel] = (),
    for_realtime: bool = False,
) -> SimFrame: ...
```

```python
def build_episode_manifest(
    *,
    episode_id: str,
    scenario_id: str | None,
    episode_status: EpisodeStatus | str,
    frame_count: int,
    dt_s: float,
    crane_configs: Sequence[CraneConfig],
    resolved_config: ResolvedConfig | Mapping[str, Any] | None = None,
    offline_labels_available: bool = False,
) -> EpisodeManifest: ...
```

```python
class VisualFrameWriter:
    def __init__(self, *, frames_path: Path, manifest_path: Path) -> None: ...
    def append_frame(self, frame: SimFrame) -> None: ...
    def write_manifest(self, manifest: EpisodeManifest) -> None: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...
```

`SimFrame.cranes` 映射规则：

- `base` 优先来自 `CraneConfig.base`；没有 config 时可用 `root_position[0:2]` 和 `0.0` 降级。
- `root`、`tip`、`hook` 来自 `CraneState`。
- `theta_rad`、`trolley_r_m`、`hook_h_m` 直接来自 `CraneState`。
- `load_size_m` 来自 `CraneState.load_size_m`。
- `current_command` 只保留前端需要的 joystick 摘要，不包含 LLM raw reason 或 prompt。

`offline_labels` 隔离规则：

- `for_realtime=True` 时，`offline_labels` 非空必须抛出 `DataExportError` 或 Pydantic validation error。
- `for_realtime=False` 时，可将同 frame 的 `OfflineRiskLabel` 转成 `OfflineFrameLabels`。
- `offline_labels` 不进入 `SimFrame.pairs` 的通用 risk 字段，必须在独立扩展字段中出现。

## 前置依赖

- Task 01 的 `SimFrame` 和 `EpisodeManifest` schema。
- Task 02 的 visual 路径。
- Task 04 的 JSONL 写入/编码策略可复用。
- `CraneState`、`WeatherState`、`Task`、`TaskQueue`、`ExecutedCommand`、`RiskPairResult`、`OfflineRiskLabel`。

## 验收标准（具体、可测试）

- `build_sim_frame()` 用最小两台塔吊状态构造合法 `SimFrame`。
- `SimFrame.type == "sim_frame"`。
- frame 字段使用 `frame`，不泄漏 `frame_index` 到输出 schema。
- `weather.visibility` 来自 `WeatherState.visibility_level`。
- `current_command` 不包含 `raw_llm_response`、provider secret 或 prompt。
- 在线风险 pair 可进入 `pairs`，包含当前距离和 `risk_level_now`。
- 实时 `build_sim_frame(..., for_realtime=True, offline_labels=[...])` 失败。
- 离线 `build_sim_frame(..., for_realtime=False, offline_labels=[...])` 成功。
- `write_visual_frame()` 生成 `visual/frames.jsonl`，每行可 `json.loads()` 并通过 `SimFrame.model_validate()`。
- `write_episode_manifest()` 生成 `visual/episode_manifest.json`，包含 L.4.1 最低字段。

## 测试要点（正常 + 边界 + 异常）

- 正常：两台塔吊、一条 medium pair、一条 event、一条 task 摘要。
- 正常：离线 frame 携带 5/10/15 秒 labels。
- 边界：无 pair、无 task、无 event 时输出空 list。
- 边界：`commands=None` 时 `current_command=None`。
- 异常：`CraneState` 三维坐标长度不合法由上游 schema 拒绝。
- 异常：实时 frame offline label 泄漏失败。
- 防泄漏：静态扫描 frames 构造器不导入 `Observation` 的 offline truth 字段，不读取 K 未来标签用于实时模式。

## 依赖关系

Task 05 依赖 Task 01、Task 02 和 Task 04。Task 07 依赖 Task 05。Task 08 需要覆盖本任务的 offline label 隔离。
